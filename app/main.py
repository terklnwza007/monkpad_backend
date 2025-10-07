from fastapi import FastAPI
from app.routers import users, tags, month_results , transactions

app = FastAPI()

# include routers
app.include_router(users.router)
app.include_router(tags.router)
app.include_router(month_results.router)
app.include_router(transactions.router)
