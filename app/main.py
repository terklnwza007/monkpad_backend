from fastapi import FastAPI
from app.routers import users, tags, month_results , transactions , auth , ocr_space
from dotenv import load_dotenv  
import os


load_dotenv()
app = FastAPI()

# include routers
app.include_router(users.router)
app.include_router(tags.router)
app.include_router(month_results.router)
app.include_router(transactions.router)
app.include_router(auth.router)
app.include_router(ocr_space.router)

