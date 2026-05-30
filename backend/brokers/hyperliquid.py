# brokers/hyperliquid.py

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Dict, List

import websockets

from brokers.base import Quote

class HyperliquidAdapter:
    name = "hyperliquid"
    prefixes = ["CRYPTO"]
    SUPPORTED_COINS: List[str] = ["BTC", "ETH", "SOL", "BNB", "DOGE", "XRP", "AVAX", "MATIC", "ARB", "OP", "SUI", "APT", "INJ", "TIA"]

    def __init__(self):
        self._ws = None
        self._queue = asyncio.Queue()
        self._subscribed = set()
        # Maps coin symbol (e.g., "BTC") to its last recorded mid price (float)
        self._last_mids: Dict[str, float] = {}
        self._recv_task: asyncio.Task | None = None
        self._running = False
        logging.info(f"{self.name} adapter initialized.")

    @staticmethod
    def _to_hl_coin(symbol: str) -> str:
        """Strips 'CRYPTO:' prefix (e.g., 'CRYPTO:BTC' -> 'BTC')."""
        if symbol.startswith("CRYPTO:"):
            return symbol[len("CRYPTO:"):]
        return symbol

    @staticmethod
    def _from_hl_coin(coin: str) -> str:
        """Adds 'CRYPTO:' prefix."""
        return f"CRYPTO:{coin}"

    async def connect(self):
        if self._running:
            return
        
        logging.info(f"Connecting to {self.NAME} websocket...")
        
        try:
            self._ws = await websockets.connect("wss://api.hyperliquid.xyz/ws")
            self._running = True
            
            # Subscribe to all mid-prices
            await self._ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "allMids"}}))
            
            # Start the background reception loop
            self._recv_task = asyncio.create_task(self._recv_loop())
            logging.info(f"{self.NAME} connected and listening for mid-prices.")

        except Exception as e:
            logging.error(f"Failed to connect to {self.NAME}: {e}")
            self._running = False
            self._ws = None
            raise

    async def subscribe(self, symbols: List[str]):
        """Records symbols to track."""
        for symbol in symbols:
            canonical = self._to_hl_coin(symbol)
            if canonical not in self._subscribed:
                self._subscribed.add(canonical)
                logging.info(f"Subscribed to {canonical} on {self.NAME}.")

    async def unsubscribe(self, symbols: List[str]):
        """Removes symbols to track."""
        for symbol in symbols:
            canonical = self._to_hl_coin(symbol)
            if canonical in self._subscribed:
                self._subscribed.remove(canonical)
                logging.info(f"Unsubscribed from {canonical} on {self.NAME}.")

    async def _recv_loop(self):
        """The main websocket message receiving and parsing loop."""
        try:
            async for message in self._ws:
                try:
                    data = json.loads(message)
                    
                    if data.get("channel") == "allMids":
                        mids: Dict[str, float] = data.get("mids", {})
                        
                        for coin_symbol, mid_price_str in mids.items():
                            try:
                                ltp = float(mid_price_str)
                            except ValueError:
                                logging.warning(f"Skipping invalid mid-price for {coin_symbol}: {mid_price_str}")
                                continue

                            # 1. Get canonical symbol (e.g., BTC)
                            canonical = coin_symbol 
                            
                            if canonical in self._subscribed:
                                # 2. Determine tracking values
                                prev_mid = self._last_mids.get(canonical, ltp)
                                
                                # 3. Calculate OHLC values based on current and previous mid
                                open_price = prev_mid if prev_mid != 0.0 else ltp
                                high_price = max(ltp, prev_mid)
                                low_price = min(ltp, prev_mid)
                                
                                # Quote parameters
                                quote = Quote(
                                    symbol=canonical, 
                                    ltp=ltp, 
                                    open=open_price, 
                                    high=high_price, 
                                    low=low_price, 
                                    close=ltp, 
                                    volume=0.0, 
                                    ts=datetime.now(timezone.utc)
                                )
                                
                                # 4. Update state and queue
                                self._last_mids[canonical] = ltp
                                await self._queue.put(quote)

                except json.JSONDecodeError:
                    logging.error("Received non-JSON message.")
                except Exception as e:
                    logging.error(f"Error processing websocket message: {e}")
                    
        except websockets.ConnectionClosedOK:
            logging.info(f"{self.NAME} websocket closed normally.")
        except websockets.ConnectionClosedError as e:
            logging.error(f"{self.NAME} websocket closed abruptly: {e}")
        except Exception as e:
            logging.error(f"Unexpected error in {_recv_loop}: {e}")
        finally:
            self._running = False
            self._ws = None


    async def quotes(self) -> AsyncIterator[Quote]:
        """Async generator yielding received Quote objects."""
        while self._running:
            try:
                # Wait for a quote to be available in the queue
                quote = await self._queue.get()
                yield quote
                self._queue.task_done()
            except asyncio.CancelledError:
                return

    async def disconnect(self):
        """Closes the websocket connection and cancels the receiving task."""
        if self._running:
            logging.info(f"Attempting to disconnect from {self.NAME}...")
            
            # 1. Cancel the background task
            if self._recv_task:
                self._recv_task.cancel()
                try:
                    await self._recv_task
                except asyncio.CancelledError:
                    pass
            
            # 2. Close the websocket connection
            if self._ws:
                await self._ws.close()
                self._ws = None
                
            self._running = False
            logging.info(f"{self.NAME} successfully disconnected.")
