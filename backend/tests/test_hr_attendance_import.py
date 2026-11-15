from uuid import uuid4

import pytest

from app.database import engine
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
