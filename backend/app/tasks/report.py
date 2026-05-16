from app.tasks.celery_app import celery_app


@celery_app.task(name="generate_report_pdf", queue="report")
def generate_report_pdf() -> str:
    return "report pdf placeholder"


@celery_app.task(name="generate_excel_export", queue="report")
def generate_excel_export() -> str:
    return "excel export placeholder"
