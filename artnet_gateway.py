import struct
import logging
import asyncio

import yaml
from yeelight import discover_bulbs
from yeelight.aio import AsyncBulb
from yeelight.main import BulbException

from aioartnet import ArtNetClient
from aioartnet.aio_artnet import swap16

from config import BULBS_INFO, DMX_START_ADDRESS, CHANNELS_PER_BULB, INPUT_FLOWS

# Configure logging for the current script
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create a console handler and set its level to DEBUG
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
# ch.setLevel(logging.INFO)

# Create a formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')

# Add the formatter to the console handler
ch.setFormatter(formatter)

# Add the console handler to the logger
logger.addHandler(ch)

# Set the logging level for aioartnet to a higher level (e.g., INFO or WARNING)
logging.getLogger('aioartnet').setLevel(logging.INFO)
# logging.getLogger('yeelight').setLevel(logging.DEBUG)

def do_nothing(param):
    logger.debug("do_nothing called with param: %s", param)


# Add these variables at module level
bulb_queues = {}

async def initialize_bulbs(bulbs_info):
    """Initialize Yeelight bulbs and prepare them for control
    
    Args:
        bulbs_info (list): List of dictionaries containing bulb IP addresses
    Returns:
        list: List of initialized AsyncBulb objects
    Raises:
        Exception: If there's a critical error that should stop the program
    """
    bulbs = []
    for bulb_info in bulbs_info:
        ip = bulb_info['ip']
        bulb = AsyncBulb(ip, auto_on=False)
        try:
            await bulb.async_listen(do_nothing)

            await bulb.async_turn_off()
            await asyncio.sleep(1)
            logger.info("Bulb %s (%s) turned off", bulb_info['name'], ip)

            await bulb.async_turn_on()
            await asyncio.sleep(1)
            logger.info("Bulb %s (%s) turned on", bulb_info['name'], ip)

            # bulb.stop_music()
            # await asyncio.sleep(1)
            # logger.info("Bulb %s (%s) stopped music", bulb_info['name'], ip)

            await bulb.async_start_music()
            await asyncio.sleep(1)
            logger.info("Bulb %s (%s) started music", bulb_info['name'], ip)

            await bulb.async_set_brightness(30)
            await asyncio.sleep(1)
            logger.info("Bulb %s (%s) set brightness to %d", bulb_info['name'], ip, 30)

            await bulb.async_set_brightness(100)
            await asyncio.sleep(1)
            logger.info("Bulb %s (%s) set brightness to %d", bulb_info['name'], ip, 100)

            bulbs.append(bulb)
        except BulbException as e:
            if len(bulbs) > 0 and bulbs[-1] == bulb:
                bulbs.pop()

                logger.error("Error initializing bulb %s (%s): %s. Skip it", bulb_info['name'], ip, e)
            continue
        except Exception as e:
            logger.error("Critical error initializing bulb at %s (%s): %s", bulb_info['name'], ip, e)
            raise  # Re-raise the exception to stop the program

    if not bulbs:
        raise Exception("No bulbs were successfully initialized. Cannot continue.")

    logger.info("Found %d bulb(s): %s", len(bulbs), [bulb._ip for bulb in bulbs])
    return bulbs

def create_dmx_mapping(bulbs, bulbs_info, channels_per_bulb=4):
    """Create mapping between DMX channels and bulbs
    
    Args:
        bulbs (list): List of AsyncBulb objects
        bulbs_info (list): List of dictionaries containing bulb configuration
        channels_per_bulb (int): Number of channels per bulb
    Returns:
        dict: Mapping of bulbs to their DMX channels
    """
    dmx_mapping = {}
    max_channel = 0

    for bulb, info in zip(bulbs, bulbs_info):
        dmx_start = info['dmx_start']
        max_channel = max(max_channel, dmx_start + channels_per_bulb - 1)

        dmx_mapping[bulb] = {
            'r': dmx_start,
            'g': dmx_start + 1,
            'b': dmx_start + 2,
            'brightness': dmx_start + 3
        }

    logger.info("DMX channels used: 1-%d", max_channel)
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
            logger.debug("Dropping state update for bulb %s as it's still processing previous state (%d, %d, %d, %d)",
                        bulb._ip, r, g, b, brightness)
            return

    except Exception as e:
        logger.error("Error queueing color update for bulb %s: %s", bulb._ip, e)
        raise e

async def bulb_state_worker(bulb):
    """Worker that processes the state updates for a specific bulb"""
    queue = bulb_queues[bulb]
    prev_r = prev_g = prev_b = prev_brightness = None

    while True:
        try:
            # Wait for the next state update
            r, g, b, brightness = await queue.get()

            try:
                brightness_percent = max(min(int((brightness / 256) * 100), 100), 0)
                logger.debug("brightness_percent is %d", brightness_percent)

                # Check RGB difference
                if (r, g, b) != (prev_r, prev_g, prev_b):
                    rgb_diff = max(
                        abs(r - (prev_r or 0)),
                        abs(g - (prev_g or 0)),
                        abs(b - (prev_b or 0))
                    )
                    duration = 200 if rgb_diff < 20 else 0
                    duration = 0
                    await bulb.async_set_rgb(r, g, b, effect="sudden", duration=duration)
                    prev_r, prev_g, prev_b = r, g, b

                # Check brightness difference
                # if brightness != prev_brightness:
                #     bright_diff = abs(brightness - (prev_brightness or 0))
                #     duration = 200 if bright_diff < 10 else 0
                #     duration = 0

                # Check brightness difference
                if brightness_percent != prev_brightness:
                    bright_diff = abs(brightness - (prev_brightness or 0))
                    duration = 200 if bright_diff < 10 else 0
                    duration = 0

                    # await bulb.async_set_brightness(brightness, effect="sudden", duration=duration)
                    await bulb.async_set_brightness(brightness_percent, effect="sudden", duration=duration)
                    prev_brightness = brightness_percent

                # Wait for 60/120ms before processing next update
                await asyncio.sleep(0.05)

            except Exception as e:
                logger.error("Error setting color for bulb %s: %s", bulb._ip, e)
                raise e
            finally:
                # Mark task as done
                queue.task_done()

        except Exception as e:
            logger.error("Error in bulb worker for %s: %s", bulb._ip, e)
            await asyncio.sleep(5)  # Prevent tight loop in case of repeated errors

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
                "Received Art-Net DMX: ver %d port_address %d seq %d channels %d from %s",
                ver, portaddress, seq, chlen, addr
            )

    for bulb, channels in dmx_mapping.items():
        r_chan = channels['r'] - 1
        g_chan = channels['g'] - 1
        b_chan = channels['b'] - 1
        brightness_chan = channels['brightness'] - 1

        r = data[8+r_chan] if r_chan < len(data) else 0
        g = data[8+g_chan] if g_chan < len(data) else 0
        b = data[8+b_chan] if b_chan < len(data) else 0

        brightness = int(data[8+brightness_chan]) if brightness_chan < len(data) else 255

        logger.debug("Updating bulb %s with color (%d, %d, %d, %d (%s))",
                    bulb._ip, r, g, b, brightness, data[8+brightness_chan])
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
    # Use configuration from config file
    bulbs_info = BULBS_INFO

    discovered_bulbs = discover_bulbs()
    discover_bulbs_summary = [{
        'ip': b['ip'],
        'id': b['capabilities']['id'],
        'power': b['capabilities']['power'],
        'model': b['capabilities']['model'],
        'support': b['capabilities']['support'],
    } for b in discovered_bulbs]

    logger.info("Discovered bulbs: %s", yaml.dump(discover_bulbs_summary))

    if len(bulbs_info) == 0:
        logger.error("No Yeelight bulbs found")
        return

    # Initialize bulbs
    bulbs = await initialize_bulbs(bulbs_info)

    # Create DMX mapping using config values
    dmx_mapping = create_dmx_mapping(bulbs,
                                   bulbs_info=bulbs_info,
                                   channels_per_bulb=CHANNELS_PER_BULB)

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
