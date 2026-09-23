"""
TachiDUBB Studio - Plug-and-Play AI Video Dubbing
==================================================
Created by TachikomaRed and smolemaru
Run: python server.py
Open: http://localhost:8910

The application itself lives in ``app/main.py``; this module is just the
entry point (`uvicorn server:app` also works).
"""
from app.main import app

if __name__ == "__main__":
    import uvicorn
    print("")
    print("+====================================================+")
    print("|  TachiDUBB Studio - AI Video Dubbing               |")
    print("|  Opening browser at http://localhost:8910...       |")
    print("|  Press Ctrl+C to stop                              |")
    print("+====================================================+")
    print("")
    uvicorn.run(app, host="0.0.0.0", port=8910, log_level="info")