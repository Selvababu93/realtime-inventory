import os
import asyncio
import logging
import json
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from database import get_db, get_async_db, engine, Base, ASYNC_DATABASE_URL
from schemas import InventoryCreate, InventoryUpdate, InventoryResponse
from models import Inventory
from notify import PostgresNotifier


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Websocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """ This method accepts a new Websocket connection and adds it to the list of active connections."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Websocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """ This method removes a Websocket connection from the active list when the client disconnects or the connection is closed """
        self.active_connections.remove(websocket)
        logger.info(f"Websocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """ This method sends a message to all connection clients and cleans up any disconnected clients. """
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error sending message to Websocket: {e}")
                disconnected.append(connection)

        # Remove disconnected connections
        for connection in disconnected:
            self.active_connections.remove(connection)


# Global instances
manager = ConnectionManager()
notifier = None


async def handle_postgres_notification(data: dict):
    """ Handle PostgreSQL notifications and broadcast to Websocket clients """
    await manager.broadcast(data)



@asynccontextmanager
async def lifespan(app:FastAPI):
    global notifier

    # Create tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")

    # Start Postgres listener
    notifier = PostgresNotifier(ASYNC_DATABASE_URL.replace("+asyncpg", ""))
    notifier.add_listener(handle_postgres_notification)

    # Start listening in background
    task = asyncio.create_task(start_postgres_listener())
    yield

    # Shutdown
    task.cancel()
    if notifier:
        await notifier.disconnect()


async def start_postgres_listener():
    """ Start the PostgreSQL listener"""
    try:
        await notifier.listen_to_channel('inventory_channel')
        await notifier.start_listening()
    except Exception as e:
        logger.error(f"Error in PostgreSQL listener: {e}")



# FastAPI and Static Files
app = FastAPI(title="Real-Time Inventory tracker", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# Routes
'''
@app.get("/")
async def read_root():
    """ Serve the main page 
    You can modify HTML on-the-fly if needed (like inserting dynamic content).
    Useful for template-like behavior without using a template engine
    """
    with open("static/index.html", "r") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)
'''
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/")
def read_index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))

@app.post("/api/inventory", response_model=InventoryResponse)
async def create_inventory_item(
    item: InventoryCreate,
    db: AsyncSession = Depends(get_async_db)
):
    """ Create a new inventory item """
    db_item = Inventory(**item.dict())
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item

@app.put("/api/inventory/{item_id}", response_model=InventoryResponse)
async def update_inventory_item(
    item_id : int,
    item_update: InventoryUpdate,
    db: AsyncSession = Depends(get_async_db)
):
    """ Update on inventory item's quantity"""
    result = await db.execute(select(Inventory).where(Inventory.id == item_id))
    db_item = result.scalar_one_or_none()

    if not db_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    
    db_item.quantity = item_update.quantity
    await db.commit()
    await db.refresh(db_item)
    return db_item

@app.delete("/api/inventory/{item_id}")
async def delete_inventory_item(
    item_id: int,
    db: AsyncSession = Depends(get_async_db)
):
    """ Delete an inventory Item"""
    result = await db.execute(select(Inventory).where(Inventory.id == item_id))
    db_item = result.scalar_one_or_none()
    if not db_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item Not Found")
    
    await db.delete(db_item)
    await db.commit()
    return {"message" : "Item deleted successfully"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """ Websocket endpoint for real-time updates"""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except Exception as e:
        manager.disconnect(websocket)
