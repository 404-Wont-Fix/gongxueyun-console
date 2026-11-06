"""Protocol constants taken from the 5.41.6 APK static analysis.

These are *client* materials built into the official app (an AES key and an MD5
suffix), not user credentials and not a server private key. They are kept in one
place so a future client update is a single-file change.
"""

from __future__ import annotations

BASE_URL = "https://api.moguding.net:9000"

# `UrlConfig.initUrl` -> static slot 0x16c8 / 0x16c4
DEFAULT_AES_KEY = "23DbtQHR2UMbH6mJ"
SIGN_SUFFIX = "3478cbbc33f84bd00d75d7dfa69e0daa"
CLIENT_ID = "428a8310cd442757ae699df5d89vmgh"

# Paths (relative to BASE_URL)
CAPTCHA_GET = "session/captcha/v1/get"
CAPTCHA_CHECK = "session/captcha/v1/check"
LOGIN = "session/user/v6/login"
PLAN_BY_STU_V3 = "practice/plan/v3/getPlanByStu"
PLAN_BY_STU_V4 = "practice/plan/v4/getPlanByStu"
PLAN_INFO_V2 = "practice/plan/v2/info"
JOB_BY_STU_V4 = "practice/job/v4/infoByStu"
ATTENDANCE_LIST = "attendence/clock/v2/listSynchro"
ATTENDANCE_LIST_TEACHER = "attendence/clock/teacher/v1/listSynchro"
ATTENDANCE_SAVE = "attendence/clock/v6/save"
ATTENDANCE_SAVE_TEACHER = "attendence/clock/teacher/v2/save"
ATTENDANCE_REPLACE = "attendence/attendanceReplace/v6/save"
CLOCK_CAPTCHA_GET = "attendence/clock/v1/get"
CLOCK_CAPTCHA_CHECK = "attendence/clock/v1/check"
ALIPAY_CREATE = "usercenter/alipay/v1/createAxdjk"
ALIPAY_QUERY = "usercenter/alipay/v1/queryAxdj"
REPORT_LIST = "practice/paper/v2/listByStu"
REPORT_INFO = "practice/paper/v2/info"
REPORT_WEEKS = "practice/paper/v3/getWeeks1"
REPORT_SAVE = "practice/paper/v6/save"
REPORT_UPDATE = "practice/paper/v3/update"
UPLOAD_TOKEN = "session/upload/v1/token"

# Business response codes
CODE_OK = 200
CODE_TOKEN_EXPIRED = 401
CODE_CAPTCHA_FAILED = 6111
CODE_CAPTCHA_EXPIRED = 6110

# Business `msg` markers used as control flow by the official client
MSG_CLICK_CAPTCHA = "302"      # 点选文字验证
MSG_ALIPAY_FACE = "303"        # 支付宝人脸/安全验证
MSG_ACCOUNT_VERIFY = "304"     # 账户风险 -> 本人安全验证

# reportType -> formType (Smi 14/16/18/20 decoded to 7/8/9/10)
REPORT_FORM_TYPES = {"day": 7, "week": 8, "month": 9, "summary": 10}
REPORT_TYPES = tuple(REPORT_FORM_TYPES)

REPORT_KEYS = (
    "address", "applyId", "applyName", "attachmentList", "commentNum",
    "commentContent", "content", "createBy", "createTime", "depName", "reject",
    "endTime", "headImg", "yearmonth", "imageList", "isFine", "latitude",
    "gpmsSchoolYear", "longitude", "planId", "planName", "reportId",
    "reportType", "reportTime", "isOnTime", "schoolId", "startTime", "state",
    "studentId", "studentNumber", "supportNum", "title", "url", "username",
    "weeks", "videoUrl", "videoTitle", "attachments", "companyName", "jobName",
    "jobId", "score", "tpJobId", "starNum", "confirmDays", "isApply",
    "compStarNum", "compScore", "compComment", "compState", "isCarryDown",
    "warningStatus", "apply", "levelEntity", "formFieldDtoList",
    "fieldEntityList", "feedback", "handleWay", "isWarning", "warningType",
)
