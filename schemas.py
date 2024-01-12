from pydantic import BaseModel
from datetime import date

class UserBase(BaseModel):
    username: str

class UserCreate(UserBase):
    password: str

class UserLogin(UserBase):
    password: str

class LeaveRequest(BaseModel):
    user_id: int
    date: date
    reason: str
    