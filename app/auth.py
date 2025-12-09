import os
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
import ssl

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from . import models, schemas
from .deps import SECRET_KEY, ALGORITHM, get_db

router = APIRouter(prefix="/auth", tags=["auth"])

# Use pbkdf2_sha256 to avoid bcrypt issues
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

RESET_TOKEN_EXPIRATION_HOURS = int(os.getenv("RESET_TOKEN_EXPIRATION_HOURS", "1"))
EMAIL_FROM = os.getenv("EMAIL_FROM", "no-reply@padpadpoker.local")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: timedelta = timedelta(hours=12)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


@router.post("/register", response_model=schemas.UserRead)
def register(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == user_in.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    existing_username = (
        db.query(models.User).filter(models.User.username == user_in.username).first()
    )
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already taken")

    user = models.User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        is_active=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


def _send_email(to_email: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = EMAIL_FROM
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    if not SMTP_HOST:
        # Fallback to console logging so the feature is usable in development
        print("=== Email sending not configured ===")
        print("To:", to_email)
        print("Subject:", subject)
        print(body)
        return

    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls(context=context)
        if SMTP_USERNAME and SMTP_PASSWORD:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(message)


def authenticate_user(db: Session, email: str, password: str) -> models.User | None:
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


# This is the endpoint Swagger will use when you press "Authorize"
@router.post("/token", response_model=TokenResponse)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    # Swagger calls this with "username" and "password" fields
    email = form_data.username  # we treat username as email
    user = authenticate_user(db, email=email, password=form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account pending approval by an administrator",
        )

    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token)


def _build_reset_link(request: Request, token: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/reset-password?token={token}"


@router.post("/forgot-password")
def forgot_password(
    payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.email == payload.email).first()

    if user:
        db.query(models.PasswordResetToken).filter(
            models.PasswordResetToken.user_id == user.id,
            models.PasswordResetToken.used.is_(False),
        ).update({models.PasswordResetToken.used: True}, synchronize_session=False)

        token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(hours=RESET_TOKEN_EXPIRATION_HOURS)
        reset_entry = models.PasswordResetToken(
            user_id=user.id, token=token, expires_at=expires_at
        )
        db.add(reset_entry)
        db.commit()

        reset_link = _build_reset_link(request, token)
        _send_email(
            to_email=user.email,
            subject="PadPad Poker password reset",
            body=(
                "We received a request to reset your PadPad Poker password.\n\n"
                f"Use the link below to choose a new password (valid for {RESET_TOKEN_EXPIRATION_HOURS} hour(s)):\n"
                f"{reset_link}\n\n"
                "If you didn't request this, you can safely ignore this email."
            ),
        )

    return {"message": "If an account exists for that email, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    token_row = (
        db.query(models.PasswordResetToken)
        .filter(models.PasswordResetToken.token == payload.token)
        .first()
    )

    if (
        not token_row
        or token_row.used
        or token_row.expires_at < datetime.utcnow()
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    user = db.query(models.User).filter(models.User.id == token_row.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="User not found for token")

    user.hashed_password = get_password_hash(payload.new_password)
    token_row.used = True
    db.commit()
    return {"message": "Password updated successfully"}
