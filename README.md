Art-Net to Yeelight Gateway
===========================

An application that receives Art-Net DMX data and controls Xiaomi Yeelight RGB smart bulbs, emulating LED RGB PAR lighting. This allows for visualizing music control signals from Engine DJ and integrates with SoundSwitch software, making each bulb appear as a dedicated device. The application trying to use "music mode" to communicate with the bulbs, ensuring low latency between music and light reactions. "music mode" is like long running tcp connection with bulbs. Sad, my smart bulbs doesn't show udp capability.

* * * * *

Project Flow and Components
--------------------------

```mermaid
flowchart LR
    subgraph Network ["Local Network (Router)"]
        A[Art-Net Source<br/>DJ Software/Controller] -->|Art-Net DMX\nUDP Port 6454| B[Art-Net Gateway App]
        B -->|Music Mode| C[Yeelight Bulb 1]
        B -->|Music Mode| D[Yeelight Bulb 2]
        B -->|Music Mode| E[Yeelight Bulb n]
    end

    subgraph Gateway ["Art-Net Gateway Processing"]
        direction TB
        B1[Receive Art-Net Packet] --> B2[Extract DMX Values]
        B2 --> B3[Map DMX Channels<br/>to Bulb Parameters]
        B3 --> B4[Convert to<br/>Yeelight Commands]
        B4 --> B5[Send color<br/>and brightenss<br/>to Bulbs]
    end

    subgraph DMX ["DMX Channel Structure"]
        direction TB
        D1[Channel 1: Red] 
        D2[Channel 2: Green]
        D3[Channel 3: Blue]
        D4[Channel 4: Reserved]
        D5[Channel 5: Brightness]
    end
```

The gateway application acts as a bridge, converting Art-Net DMX data into Yeelight-compatible commands.

PC with running artnet_gateway must be connected in artnet network and to smart bulbs network. In my case is the same, its just mobile wifi router.
* * * * *

### Sequence Diagram

```mermaid
sequenceDiagram
    participant S as Art-Net Source
    participant G as Gateway App
    participant B as Yeelight Bulb
    
    Note over G: Start Application
    G->>B: Discover Bulbs (config + )
    G->>B: Stop Music Mode
    G->>B: Set Initial Brightness
    G->>B: Start Music Mode
    
    loop DMX Processing
        S->>G: Receive Art-Net DMX Packet
        G->>G: Extract RGB + Brightness
        G->>B: Update bulb Color
        G->>B: Update bulb Brightness
    end
    
    Note over G: On Shutdown
    G->>B: Stop Music Mode
```
