import asyncio
from aioartnet_local.aioartnet.aio_artnet import ArtNetNode
# from yeelight import Bulb, discover_bulbs
import sys
import struct
import logging
from aioartnet import ArtNetClient
from aioartnet.aio_artnet import swap16
from pyyeelight.yeelight.aio import AsyncBulb
import time

# Configure logging for the current script
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create a console handler and set its level to DEBUG
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

# Create a formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Add the formatter to the console handler
ch.setFormatter(formatter)

# Add the console handler to the logger
logger.addHandler(ch)

# Set the logging level for aioartnet to a higher level (e.g., INFO or WARNING)
logging.getLogger('aioartnet').setLevel(logging.INFO)
logging.getLogger('yeelight').setLevel(logging.DEBUG)

def do_nothing(param):
    pass

# Add these variables at module level
bulb_queues = {}

async def initialize_bulbs(bulbs_info):
    """Initialize Yeelight bulbs and prepare them for control
    
    Args:
        bulbs_info (list): List of dictionaries containing bulb IP addresses
    Returns:
        list: List of initialized AsyncBulb objects
    """
    bulbs = []
    for bulb_info in bulbs_info:
        ip = bulb_info['ip']
        bulb = AsyncBulb(ip, auto_on=False)
        try:
            await bulb.async_listen(do_nothing)
            await asyncio.sleep(1)
            await bulb.async_stop_music()
            await bulb.async_set_brightness(100)
            await bulb.async_start_music()
            # await asyncio.sleep(1)
            # await bulb.async_turn_on()
            await asyncio.sleep(1)
            bulbs.append(bulb)
        except Exception as e:
            logger.error(f"Error initializing bulb at {ip}: {e}")
            raise e
    
    logger.info(f"Found {len(bulbs)} bulb(s): {[bulb._ip for bulb in bulbs]}")
    return bulbs

def create_dmx_mapping(bulbs, start_address=1, channels_per_bulb=5):
    """Create mapping between DMX channels and bulbs
    
    Args:
        bulbs (list): List of AsyncBulb objects
        start_address (int): Starting DMX address
        channels_per_bulb (int): Number of channels per bulb
    Returns:
        dict: Mapping of bulbs to their DMX channels
    """
    dmx_mapping = {}
    for index, bulb in enumerate(bulbs):
        dmx_start = start_address + index * channels_per_bulb
        dmx_mapping[bulb] = {
            'r': dmx_start,
            'g': dmx_start + 1,
            'b': dmx_start + 2,
            'brightness': dmx_start + 4
        }
    max_channel = start_address + len(bulbs) * channels_per_bulb - 1
    logger.info(f"DMX channels used: {start_address}-{max_channel}")
    return dmx_mapping

async def update_bulb_color(bulb, r, g, b, brightness):
    """Update bulb color and brightness if enough time has passed since last command
    
    Args:
        bulb: AsyncBulb instance
        r (int): Red value (0-255)
        g (int): Green value (0-255) 
        b (int): Blue value (0-255)
        brightness (int): Brightness value (0-255)
    """
    # Initialize queue for this bulb if it doesn't exist
    if bulb not in bulb_queues:
        bulb_queues[bulb] = asyncio.Queue(maxsize=1)
        # Start the worker for this bulb
        asyncio.create_task(bulb_state_worker(bulb))

    try:
        # Try to put the new state in the queue, drop if queue is full
        try:
            bulb_queues[bulb].put_nowait((r, g, b, brightness))
        except asyncio.QueueFull:
            logger.debug(f"Dropping state update for bulb {bulb._ip} as it's still processing previous state ({r}, {g}, {b}, {brightness})")
            return

    except Exception as e:
        logger.error(f"Error queueing color update for bulb {bulb._ip}: {e}")
        raise e

async def bulb_state_worker(bulb):
    """Worker that processes the state updates for a specific bulb"""
    queue = bulb_queues[bulb]
    
    while True:
        try:
            # Wait for the next state update
            r, g, b, brightness = await queue.get()
            
            try:
                brightness_percent = max(min(int((brightness / 255) * 100), 100), 1)
                
                # Apply the state change
                await bulb.async_set_rgb(r, g, b, effect="sudden", duration=0)
                await bulb.async_set_brightness(brightness, effect="sudden", duration=200)
                
                # Wait for 60/120ms before processing next update
                await asyncio.sleep(0.04)
                
            except Exception as e:
                logger.error(f"Error setting color for bulb {bulb._ip}: {e}")
                raise e
            finally:
                # Mark task as done
                queue.task_done()
                
        except Exception as e:
            logger.error(f"Error in bulb worker for {bulb._ip}: {e}")
            await asyncio.sleep(1)  # Prevent tight loop in case of repeated errors

async def process_dmx(addr, data, dmx_mapping):
    """Process incoming DMX data and update bulbs accordingly
    
    Args:
        addr: DMX address
        data: DMX data array
        dmx_mapping (dict): Mapping of bulbs to DMX channels
    """
    # logger.info(f"Processing DMX data: addr={addr}, data={[int(byte) for byte in data[:10]]}")
    ver, seq, phys, sub, net, chlen = struct.unpack("<HBBBBH", data[0:8])
    ver = swap16(ver)
    chlen = swap16(chlen)
    portaddress = sub + (net << 8)

    if portaddress != 0:
        return

    logger.debug(
                f"Received Art-Net DMX: ver {ver} port_address {portaddress} seq {seq} channels {chlen} from {addr}"
            )

    for bulb, channels in dmx_mapping.items():
        r_chan = channels['r'] - 1
        g_chan = channels['g'] - 1
        b_chan = channels['b'] - 1
        brightness_chan = channels['brightness'] - 1

        r = data[8+r_chan] if r_chan < len(data) else 0
        g = data[8+g_chan] if g_chan < len(data) else 0
        b = data[8+b_chan] if b_chan < len(data) else 0

        brightness = data[8+brightness_chan] * 2 if brightness_chan < len(data) else 255

        logger.debug(f"Updating bulb {bulb._ip} with color ({r}, {g}, {b}, {brightness})")
        await update_bulb_color(bulb, r, g, b, brightness)

async def cleanup_bulbs(bulbs):
    """Clean up bulb connections and pending tasks
    
    Args:
        bulbs (list): List of AsyncBulb objects
    """
    for bulb in bulbs:
        await bulb.async_stop_music()
    
    pending = [task for task in asyncio.all_tasks() if not task.done()]
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

async def main():
    # Initialize bulb information
    bulbs_info = [{'ip': '192.168.108.149'}]
    
    if len(bulbs_info) == 0:
        logger.error("No Yeelight bulbs found")
        return

    # Initialize bulbs
    bulbs = await initialize_bulbs(bulbs_info)
    
    # Create DMX mapping
    dmx_mapping = create_dmx_mapping(bulbs)
    
    # Create Art-Net client and connect
    client = ArtNetClient()
    await client.connect()
    universe = client.set_port_config("0:0:0", isoutput=True)

    # Define callback wrapper to include dmx_mapping
    def dmx_callback(addr, data):
        asyncio.create_task(process_dmx(addr, data, dmx_mapping))

    # Register callback
    client.protocol.handlers[0x5000] = dmx_callback
    
    logger.info("Listening for Art-Net DMX data...")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Exiting...")
    finally:
        await cleanup_bulbs(bulbs)

if __name__ == '__main__':
    asyncio.run(main())
