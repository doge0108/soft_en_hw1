from fastapi import FastAPI, Depends, HTTPException, status, Request, Form, APIRouter
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from dateutil.relativedelta import relativedelta
import models, schemas, utils
from models import SessionLocal, engine, LeaveRequest, User
from fastapi.templating import Jinja2Templates
from datetime import date, datetime


models.Base.metadata.create_all(bind=engine)

app = FastAPI()
router = APIRouter()
app.add_middleware(SessionMiddleware, secret_key="poonpoon")
templates = Jinja2Templates(directory="templates")

def yesno(value):
    return "Yes" if value else "No"

templates.env.filters['yesno'] = yesno


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/register/")
def register_user(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.username == username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_password = utils.hash_password(password)
    new_user = models.User(username=username, password=hashed_password)

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"username": new_user.username}

@app.get("/register/")
async def show_register_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

def authenticate_user(db: Session, username: str, password: str):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not utils.verify_password(password, user.hashed_password):
        return False
    return user

@app.post("/login/")
async def login_user(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.username == username).first()
    if not db_user or not utils.verify_password(password, db_user.password):
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid username or password"})
    if db_user and utils.verify_password(password, db_user.password):
        request.session['user_id'] = db_user.id
        return RedirectResponse(url="/leave-requests/", status_code=303)
    else:
        raise HTTPException(status_code=400, detail="Incorrect username or password")

@app.get("/login/")
async def show_login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/logout/")
async def logout_user(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login/", status_code=303)

@app.post("/request_leave/")
def request_leave(leave: schemas.LeaveRequest, db: Session = Depends(get_db)):
    db_leave = models.LeaveRequest(**leave.dict())
    db.add(db_leave)
    db.commit()
    db.refresh(db_leave)
    return db_leave

def get_current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get('user_id')
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    return db.query(models.User).filter(models.User.id == user_id).first()


@app.get("/leave-requests/")
async def show_leave_requests(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get('user_id')
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    current_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")

    leave_requests = db.query(models.LeaveRequest, models.User.username).\
        join(models.User, models.User.id == models.LeaveRequest.user_id).\
        order_by(models.LeaveRequest.date.asc()).\
        all()

    return templates.TemplateResponse("leave_requests.html", {
        "request": request, 
        "leave_requests": leave_requests,
        "user": current_user,
        "now": datetime.now().date()
    })

@app.post("/submit-leave-request/")
async def submit_leave_request(request: Request, leave_date: date = Form(...), reason: str = Form(...), db: Session = Depends(get_db)):
    user_id = request.session.get('user_id')
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    existing_leave = db.query(models.LeaveRequest).filter(
        models.LeaveRequest.user_id == user_id, 
        models.LeaveRequest.date == leave_date).first()
    if existing_leave:
        return JSONResponse(status_code=400, content={"detail": "Leave already requested for this date"})

    current_year = leave_date.year
    leave_days_this_year = db.query(func.count(models.LeaveRequest.id)).filter(
        models.LeaveRequest.user_id == user_id, 
        func.extract('year', models.LeaveRequest.date) == current_year).scalar()
    if leave_days_this_year >= 10:
        return JSONResponse(status_code=400, content={"detail": "Annual leave quota exceeded"})

    if leave_date > date.today() + relativedelta(months=+2):
        return JSONResponse(status_code=400, content={"detail": "Cannot request leave more than 2 months in advance"})

    new_leave_request = models.LeaveRequest(user_id=user_id, date=leave_date, reason=reason)
    db.add(new_leave_request)
    db.commit()
    return JSONResponse(status_code=200, content={"message": "Leave request submitted successfully"})

@app.post("/approve-leave/{leave_id}")
async def approve_leave(leave_id: int, request: Request, db: Session = Depends(get_db)):
    if not is_admin(request, db):
        raise HTTPException(status_code=403, detail="Not authorized to approve leave")

    if not approve_leave_request(leave_id, db):
        raise HTTPException(status_code=404, detail="Leave request not found")

    return JSONResponse(content={"message": "Leave request approved"})

@app.delete("/delete-leave-request/{leave_id}")
async def delete_leave_request(leave_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get('user_id')
    leave_request = db.query(models.LeaveRequest).filter(models.LeaveRequest.id == leave_id).first()
    
    if not leave_request:
        raise HTTPException(status_code=404, detail="Leave request not found")

    if user_id != leave_request.user_id and not is_admin(user_id, db):
        raise HTTPException(status_code=403, detail="Not authorized to delete this leave request")

    if leave_request.date < date.today():
        raise HTTPException(status_code=400, detail="Cannot delete past leave requests")

    db.delete(leave_request)
    db.commit()

    return {"message": "Leave request successfully deleted"}


def is_admin(request: Request, db: Session) -> bool:
    user_id = request.session.get('user_id')
    admin_user = db.query(User).filter(User.username == "admin").first()
    return user_id == admin_user.id

def approve_leave_request(leave_id: int, db: Session) -> bool:
    leave_request = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if leave_request:
        leave_request.approved = True
        db.commit()
        return True
    return False