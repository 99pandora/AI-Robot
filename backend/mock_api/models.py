"""Mock API 的强类型响应模型。"""

from datetime import date, datetime, time

from pydantic import BaseModel, Field


class AttendanceRecord(BaseModel):
    attendance_id: str = Field(alias="attendanceId", description="考勤记录 ID")
    user_id: str = Field(alias="userId", description="员工编号，例如 U001")
    user_name: str = Field(alias="userName", description="员工姓名")
    dept_name: str = Field(alias="deptName", description="部门名称")
    check_in_date: date = Field(alias="checkInDate", description="考勤日期")
    check_in_time: time | None = Field(alias="checkInTime", description="打卡时间")
    check_out_time: time | None = Field(alias="checkOutTime", description="下班时间")
    attendance_status: str = Field(alias="attendanceStatus", description="机器状态码")
    status_desc: str = Field(alias="statusDesc", description="面向用户的状态说明")
    work_hours: float = Field(alias="workHours", description="工作时长（小时）")
    leave_type: str | None = Field(alias="leaveType", description="请假或出差类型")
    leave_hours: float = Field(alias="leaveHours", description="请假时长（小时）")
    remark: str = Field(description="备注")
    create_time: datetime = Field(alias="createTime", description="记录生成时间")


class OrderRecord(BaseModel):
    order_id: str = Field(alias="orderId", description="订单 ID")
    customer_name: str = Field(alias="customerName", description="客户名称")
    amount: float = Field(description="订单金额")
    status: str = Field(description="订单状态")
    create_time: datetime = Field(alias="createTime", description="订单创建时间")
