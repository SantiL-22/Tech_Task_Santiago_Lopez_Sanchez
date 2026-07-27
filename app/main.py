from fastapi import FastAPI #Import fast API

app = FastAPI(title="AI Collector - Tool API") #Create fast API instance


@app.get("/health") #Health check endpoint
def health():
    return {"ok": True, "service": "collector-tools"} #Return health check