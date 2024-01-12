from fastapi import FastAPI
from fastapi import Depends
from sqlalchemy.orm import Session
import models, schemas

app = FastAPI()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/register/")
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    pass

@app.post("/login/")
def login_user(user: schemas.UserLogin, db: Session = Depends(get_db)):
    pass

@app.post("/request_leave/")
def request_leave(leave: schemas.LeaveRequest, db: Session = Depends(get_db)):
    pass

@app.post("/view_leaves/")
def view_leaves(db: Session = Depends(get_db)):
    pass