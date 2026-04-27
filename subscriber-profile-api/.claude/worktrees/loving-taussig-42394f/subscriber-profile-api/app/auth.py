import jwt
from fastapi import HTTPException, Header
from app.config import JWT_SKIP_VERIFY, JWT_PUBLIC_KEY, JWT_ALGORITHM


async def require_auth(authorization: str = Header(default="")):
    if JWT_SKIP_VERIFY:
        return {"sub": "dev"}

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization[7:]
    try:
        payload = jwt.decode(token, JWT_PUBLIC_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
