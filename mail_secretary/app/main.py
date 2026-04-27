from fastapi import FastAPI

app = FastAPI(title="mail-secretary")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/jobs/poll-mail")
def poll_mail() -> dict:
    return {"status": "accepted", "processed": 0}


@app.post("/jobs/reprocess")
def reprocess(message_id: str) -> dict:
    return {"status": "accepted", "message_id": message_id}


@app.get("/version")
def version() -> dict:
    return {"version": "v1"}
