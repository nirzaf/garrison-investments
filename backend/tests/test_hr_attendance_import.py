import asyncio
import io
import json
import stat
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.database import AsyncSessionLocal, engine
from app.models.hr import HrEmployee, HrWorkCalendar
from scripts import garrisonctl
from scripts.garrisonctl_common import AUTH, CONFLICT, VALIDATION
from tests.test_hr import _auth, _client, _create_portal_user, _login, skip_if_database_unavailable


@pytest.fixture(autouse=True)
async def isolated_pool():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_attendance_csv_review_revision_and_period_lock() -> None:
    await skip_if_database_unavailable()
    _, recorder_email, pw = await _create_portal_user("hr_manager")
    _, approver_email, _ = await _create_portal_user("hr_manager", pw)
    _, staff_email, _ = await _create_portal_user("quantity_surveyor", pw)
    async with _client() as client:
        recorder = _auth(await _login(client, recorder_email, pw))
        approver = _auth(await _login(client, approver_email, pw))
        staff = _auth(await _login(client, staff_email, pw))
        base = "/api/v1/hr"
        code = f"IMP-{uuid4().hex[:8]}"
        employee = await client.post(
            f"{base}/employees",
            headers=recorder,
            json={
                "employee_code": code,
                "first_name": "Synthetic",
                "last_name": "CSV",
                "employment_status": "active",
            },
        )
        assert employee.status_code == 201, employee.text
        employee_id = employee.json()["id"]
        header = "employee_code,work_date,attendance_status,worked_hours,check_in_at,check_out_at\n"
        row = (
            f"{code},2027-02-03,present,7.00,2027-02-03T08:00:00+05:30,2027-02-03T15:00:00+05:30\n"
        )

        async def upload(path, content, headers, digest=None):
            return await client.post(
                f"{base}/attendance/imports/{path}",
                headers=headers,
                files={"file": ("attendance.csv", content.encode(), "text/csv")},
                data={"expected_digest": digest} if digest else None,
            )

        assert (await upload("preview", header + row, staff)).status_code == 403
        duplicate = await upload("preview", header + row + row, recorder)
        assert duplicate.json()["digest"] is None and duplicate.json()["items"][1]["error"]
        invalid = await upload("preview", header + row.replace("7.00", "8.00"), recorder)
        assert (
            invalid.json()["digest"] is None
            and "clock interval" in invalid.json()["items"][0]["error"]
        )
        preview = await upload("preview", header + row, recorder)
        assert preview.status_code == 200, preview.text
        digest = preview.json()["digest"]
        assert digest
        params = {"employee_id": employee_id}
        assert (await client.get(f"{base}/attendance", headers=recorder, params=params)).json()[
            "total"
        ] == 0
        changed = await upload("apply", header + row.replace("7.00", "6.00"), recorder, digest)
        assert changed.status_code == 409
        assert (await upload("apply", header + row, recorder, digest)).status_code == 201
        assert (await upload("apply", header + row, recorder, digest)).status_code == 409
        entries = (await client.get(f"{base}/attendance", headers=approver, params=params)).json()[
            "items"
        ]
        assert (
            len(entries) == 1
            and entries[0]["source"] == "import"
            and entries[0]["status"] == "submitted"
        )
        review = f"{base}/attendance/{entries[0]['id']}/decision"
        approval = {"decision": "approved", "expected_revision": 1}
        assert (await client.post(review, headers=recorder, json=approval)).status_code == 403

        timesheet = await client.post(
            f"{base}/timesheets",
            headers=recorder,
            json={
                "employee_id": employee_id,
                "period_start": "2027-02-01",
                "period_end": "2027-02-05",
                "regular_hours": "7.00",
                "submit": True,
            },
        )
        assert timesheet.status_code == 201, timesheet.text
        timesheet_review = f"{base}/timesheets/{timesheet.json()['id']}/decision"
        assert (
            await client.post(timesheet_review, headers=approver, json={"decision": "approved"})
        ).status_code == 200
        assert (
            await client.post(timesheet_review, headers=approver, json={"decision": "locked"})
        ).status_code == 409
        correction_body = {
            "employee_id": employee_id,
            "work_date": "2027-02-03",
            "requested_status": "present",
            "requested_worked_hours": "6.50",
            "reason": "Synthetic correction",
        }
        correction_path = f"{base}/attendance/corrections"
        correction = await client.post(correction_path, headers=recorder, json=correction_body)
        assert correction.status_code == 201, correction.text
        assert (await client.post(review, headers=approver, json=approval)).status_code == 200
        correction_review = f"{correction_path}/{correction.json()['id']}/decision"
        stale = await client.post(
            correction_review, headers=approver, json={"decision": "approved"}
        )
        assert stale.status_code == 409 and stale.json()["error_code"] == "REVISION_CONFLICT"
        assert (
            await client.post(correction_review, headers=approver, json={"decision": "rejected"})
        ).status_code == 200
        assert (
            await client.post(timesheet_review, headers=approver, json={"decision": "locked"})
        ).status_code == 200
        assert (
            await client.post(correction_path, headers=recorder, json=correction_body)
        ).status_code == 409


@pytest.mark.asyncio
async def test_attendance_csv_previews_overnight_clocks_and_blocks_missing_punches() -> None:
    await skip_if_database_unavailable()
    _, email, password = await _create_portal_user("hr_manager")
    async with AsyncSessionLocal() as session:
        calendar = HrWorkCalendar(
            code=f"NIGHT-{uuid4().hex[:8]}",
            name="Synthetic overnight attendance",
            effective_from=date(2027, 2, 3),
            effective_to=date(2027, 2, 4),
            timezone="Asia/Colombo",
            work_days_json=["WED", "THU"],
            daily_hours=Decimal("8"),
            status="published",
        )
        session.add(calendar)
        await session.flush()
        employee = HrEmployee(
            employee_code=f"NIGHT-{uuid4().hex[:8]}",
            first_name="Synthetic",
            last_name="Overnight",
            full_name="Synthetic Overnight",
            employment_status="active",
            work_calendar_id=calendar.id,
        )
        session.add(employee)
        await session.flush()
        code, employee_id, calendar_id = employee.employee_code, employee.id, calendar.id
        await session.commit()

    header = "employee_code,work_date,attendance_status,worked_hours,check_in_at,check_out_at\n"
    start, end = "2027-02-03T22:00:00+05:30", "2027-02-04T06:00:00+05:30"
    valid = f"{code},2027-02-03,present,8.00,{start},{end}\n"
    partial = f"{code},2027-02-04,present,4.00,2027-02-04T22:00:00+05:30,\n"
    wrong_local_date = valid.replace(start, "2027-02-03T19:00:00Z")
    root = "/api/v1/hr/attendance"
    async with _client() as client:
        auth = _auth(await _login(client, email, password))

        async def upload(rows: str, digest: str | None = None):
            suffix = "apply" if digest else "preview"
            return await client.post(
                f"{root}/imports/{suffix}",
                headers=auth,
                files={"file": ("attendance.csv", (header + rows).encode(), "text/csv")},
                data={"expected_digest": digest} if digest else None,
            )

        async def entries():
            response = await client.get(
                root, headers=auth, params={"employee_id": str(employee_id)}
            )
            assert response.status_code == 200
            return response.json()

        mixed = await upload(valid + partial)
        assert mixed.status_code == 200
        assert mixed.headers["cache-control"] == "no-store"
        assert mixed.json()["digest"] is None
        overnight, incomplete = mixed.json()["items"]
        assert overnight["check_in_at"] == start and overnight["check_out_at"] == end
        assert "both clock times" in incomplete["error"]
        assert (await upload(valid + partial, "0" * 64)).status_code == 409
        # The source timestamp is February 3 UTC, but February 4 in the employee's calendar.
        wrong_local_date = wrong_local_date.replace(end, "2027-02-04T04:00:00+05:30")
        rejected = (await upload(wrong_local_date.replace("8.00", "3.00"))).json()
        assert rejected["digest"] is None and "calendar timezone" in rejected["items"][0]["error"]
        assert (await entries())["total"] == 0

        preview = await upload(valid)
        digest = preview.json()["digest"]
        assert digest
        applied = await upload(valid, digest)
        assert applied.status_code == 201 and applied.json()["digest"] == digest
        assert preview.json()["items"][0]["entry_id"] is None
        assert applied.headers["cache-control"] == "no-store"
        record = (await entries())["items"][0]
        assert applied.json()["items"] == [{**preview.json()["items"][0], "entry_id": record["id"]}]
        assert record["work_date"] == "2027-02-03"
        assert record["calendar_id"] == str(calendar_id) and record["status"] == "submitted"
        assert datetime.fromisoformat(record["check_in_at"]) == datetime.fromisoformat(start)
        assert datetime.fromisoformat(record["check_out_at"]) == datetime.fromisoformat(end)


@pytest.mark.asyncio
async def test_attendance_cli_reviews_private_csv_and_verifies_committed_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await skip_if_database_unavailable()
    monkeypatch.setenv("GARRISON_API_BASE_URL", "http://127.0.0.1:8425")
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)
    _, maker_email, password = await _create_portal_user("hr_manager")
    _, other_email, _ = await _create_portal_user("hr_manager", password)
    _, staff_email, _ = await _create_portal_user("quantity_surveyor", password)
    code = f"CLI-TIME-{uuid4().hex[:8]}"
    start = "2027-10-04T22:30:00+05:30"
    end = "2027-10-05T06:00:00+05:30"
    header = "employee_code,work_date,attendance_status,worked_hours,check_in_at,check_out_at\n"
    good_file = header + f"{code},2027-10-04,present,7.50,{start},{end}\n"
    source = tmp_path / "private-attendance.csv"
    source.touch(mode=0o600)
    source.write_text(good_file.removesuffix(end + "\n") + "\n")
    async with _client() as client:
        maker = await _login(client, maker_email, password)
        other = await _login(client, other_email, password)
        staff = await _login(client, staff_email, password)
        employee = await client.post(
            "/api/v1/hr/employees",
            headers=_auth(maker),
            json={"employee_code": code, "first_name": "Synthetic", "last_name": "Attendance"},
        )
        assert employee.status_code == 201
        loop = asyncio.get_running_loop()

        def transport(request: httpx.Request) -> httpx.Response:
            response = asyncio.run_coroutine_threadsafe(
                client.request(
                    request.method,
                    request.url.raw_path.decode("ascii"),
                    headers=request.headers,
                    content=request.content,
                ),
                loop,
            ).result(timeout=10)
            return httpx.Response(
                response.status_code, headers=response.headers, content=response.content
            )

        async def invoke(token: str, *args: str, expected: int = 0) -> dict:
            monkeypatch.setenv("GARRISON_ACCESS_TOKEN", token)
            stdout, stderr = io.StringIO(), io.StringIO()
            exit_code = await asyncio.to_thread(
                garrisonctl.run,
                ["hr", "attendance", "import", "--file", str(source), "--json", *args],
                transport=httpx.MockTransport(transport),
                stdout=stdout,
                stderr=stderr,
            )
            output = stdout.getvalue() + stderr.getvalue()
            assert all(value not in output for value in (code, start, end, source.name))
            assert exit_code == expected, output
            return json.loads(stdout.getvalue())

        await invoke(staff, "--dry-run", expected=AUTH)
        invalid_review = tmp_path / "invalid-review.json"
        blocked = await invoke(
            maker, "--dry-run", "--output", str(invalid_review), expected=VALIDATION
        )
        assert blocked["data"]["invalid_rows"] == [2]
        assert "both clock times" in json.loads(invalid_review.read_text())["items"][0]["error"]
        source.write_text(good_file)
        review = tmp_path / "approved-review.json"
        plan = (await invoke(maker, "--dry-run", "--output", str(review)))["data"]
        assert stat.S_IMODE(review.stat().st_mode) == 0o600
        item = json.loads(review.read_text())["items"][0]
        assert item["check_out_at"] == end and item["entry_id"] is None
        apply = ("--apply", "--expect", plan["plan_sha256"])
        await invoke(other, *apply, expected=CONFLICT)
        source.write_text(good_file.replace("7.50", "7.00"))
        await invoke(maker, *apply, expected=CONFLICT)
        source.write_text(good_file)
        receipt = (await invoke(maker, *apply))["data"]
        assert receipt["row_count"] == 1 and receipt["entries"][0]["row"] == 2
        entry_id = receipt["entries"][0]["entry_id"]
        persisted = await client.get(f"/api/v1/hr/attendance/{entry_id}", headers=_auth(maker))
        record = persisted.json()
        assert record["employee_id"] == employee.json()["id"] and record["status"] == "submitted"
        assert record["source"] == "import" and record["work_date"] == "2027-10-04"
        assert datetime.fromisoformat(record["check_out_at"]) == datetime.fromisoformat(end)
        await invoke(maker, *apply, expected=CONFLICT)
