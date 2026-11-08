import os
from datetime import date

from tema_ops.notify import send_email
from tema_ops.wolt.excel_report import build_report

REPORT_PATH = "reports/wolt_report.xlsx"

if __name__ == "__main__":
    build_report(REPORT_PATH)
    send_email(
        os.environ["WOLT_REPORT_TO"],
        f"თემის Wolt-ის რეპორტი {date.today():%d.%m.%Y}",
        "ამ წერილს თან ერთვის Wolt-ის ყველა ფილიალის ანგარიში, გუშინდელი დღის მონაცემების ჩათვლით.",
        attachment=REPORT_PATH,
    )
    print("Report sent")
