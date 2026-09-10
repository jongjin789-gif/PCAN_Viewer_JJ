"""Raw DBC counters; state is committed only after a successful send."""
from src.tx_crc import apply_crcs


def counter_payload(message, payload, counters, states):
    raw = message.decode(payload, decode_choices=False, scaling=False)
    next_states = dict(states)
    changed = []
    for name, cfg in counters.items():
        if cfg['mode'] in ('none', 'crc8', 'crc16') or name not in raw:
            continue
        low, high, step = cfg['min'], cfg['max'], cfg['step']
        value, direction = states.get(name, (raw[name], -1 if cfg['mode'] == 'down' else 1))
        value = max(low, min(high, value))
        raw[name] = value
        changed.append(message.get_signal_by_name(name))
        if cfg['mode'] == 'up':
            following = low if value + step > high else value + step
        elif cfg['mode'] == 'down':
            following = high if value - step < low else value - step
        else:
            if value >= high:
                direction = -1
            elif value <= low:
                direction = 1
            following = max(low, min(high, value + direction * step))
        next_states[name] = (following, direction)
    encoded = message.encode(raw, scaling=False, strict=False)
    result = bytearray(payload)
    # Copy only changed signal bits, retaining padding and other signal values.
    for sig in changed:
        bit = sig.start
        for _ in range(sig.length):
            byte, shift = divmod(bit, 8)
            mask = 1 << shift
            result[byte] = (result[byte] & ~mask) | (encoded[byte] & mask)
            bit = bit + 1 if sig.byte_order == 'little_endian' else (bit + 15 if shift == 0 else bit - 1)
    if any(cfg.get('mode') in ('crc8', 'crc16') for cfg in counters.values()):
        result = apply_crcs(message, result, counters)
    return bytes(result), next_states
