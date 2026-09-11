import asyncio
import sys

# asyncpg's connection-close/cancel path is incompatible with Windows'
# default ProactorEventLoop. Only affects local Windows test runs; Linux
# (Docker, Jenkins, the VPS) is unaffected.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
