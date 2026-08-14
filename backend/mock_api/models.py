"""Mock API 的强类型响应模型。"""

from datetime import date, datetime, time

from pydantic import BaseModel, Field


class AttendanceRecord(BaseModel):
    attendance_id: str = Field(alias="attendanceId")
    user_id: str = Field(alias="userId")
    user_name: str = Field(alias="userName")
    dept_name: str = Field(alias="deptName")
    check_in_date: date = Field(alias="checkInDate")
    check_in_time: time | None = Field(alias="checkInTime")
    check_out_time: time | None = Field(alias="checkOutTime")
    attendance_status: str = Field(alias="attendanceStatus")
    status_desc: str = Field(alias="statusDesc")
    work_hours: float = Field(alias="workHours")
    leave_type: str | None = Field(alias="leaveType")
    leave_hours: float = Field(alias="leaveHours")
    remark: str
    create_time: datetime = Field(alias="createTime")


class OrderRecord(BaseModel):
    order_id: str = Field(alias="orderId")
    customer_name: str = Field(alias="customerName")
    amount: float
    status: str
    create_time: datetime = Field(alias="createTime")
