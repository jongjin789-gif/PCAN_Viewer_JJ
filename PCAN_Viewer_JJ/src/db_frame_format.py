"""Preserve FD metadata that database parsers may omit."""
import re
import cantools


def is_fd_format(value):
    normalized = re.sub(r'[^a-z0-9]', '', str(value).lower())
    return normalized in {'fd', 'fdstandard', 'fdextended', 'fdcan', 'canfd',
                          'standardcanfd', 'extendedcanfd', 'standardfd', 'extendedfd'}


def message_is_fd(message):
    if message.is_fd or message.length > 8:
        return True
    dbc = getattr(message, 'dbc', None)
    attributes = getattr(dbc, 'attributes', {})
    for key in ('VFrameFormat', 'BusType', 'Type'):
        attribute = attributes.get(key)
        if attribute is None:
            continue
        value = attribute.value
        choices = getattr(getattr(attribute, 'definition', None), 'choices', None)
        if isinstance(value, int) and choices and 0 <= value < len(choices):
            value = choices[value]
        if is_fd_format(value):
            return True
    return False


def load_sym_with_fd(content):
    fd_names = set()
    name = None
    lines = []
    for line in content.splitlines():
        if re.match(r'^\s*FormatVersion\s*=', line) and '//' not in line:
            line += ' // Symbol file'
        section = re.match(r'^\s*\[([^\]]+)\]', line)
        if section:
            name = section.group(1)
        match = re.match(r'^\s*Type\s*=\s*(.*?)\s*(?://.*)?$', line, re.IGNORECASE)
        if match and is_fd_format(match.group(1)):
            fd_names.add(name)
            # Normalize aliases, including the two-word "FD CAN", for cantools.
            line = 'Type=FDExtended' if 'extended' in match.group(1).lower() else 'Type=FDStandard'
        lines.append(line)
    database = cantools.database.load_string('\n'.join(lines), database_format='sym', strict=False)
    for message in database.messages:
        if message.name in fd_names:
            message.is_fd = True
    return database
