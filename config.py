# Configuration for Yeelight bulbs
BULBS_INFO = [
    # {
    #     'ip': '192.168.108.131', 
    #     'name': 'Party1',
    #     'dmx_start': 1  # First bulb starts at channel 1
    # },
    # {
    #     'ip': '192.168.108.112', 
    #     'name': 'Party2',
    #     'dmx_start': 6  # Second bulb starts at channel 6
    # },
    {
        'ip': '192.168.108.131',
        'name': 'lamp_in_corner',
        'dmx_start': 1
    },
    {
        'ip': '192.168.108.149',
        'name': 'desktop lamp',
        'dmx_start': 5
    },
    {'ip': '192.168.108.249', 'name': 'bedroom lamp 1', 'dmx_start': 9},
    # {'ip': '192.168.108.110', 'name': 'Corner Lamp (bathroom)', 'dmx_start': 21},
    {'ip': '192.168.108.189', 'name': 'Kitchen', 'dmx_start': 13},
]

# You can add other configuration parameters here
DMX_START_ADDRESS = 1
CHANNELS_PER_BULB = 4
INPUT_FLOWS = 4