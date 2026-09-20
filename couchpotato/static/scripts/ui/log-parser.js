// Shared, bounded parsing for the standalone and Settings log panels.

const RAW_LEVELS = ['ERROR', 'WARNING', 'INFO', 'DEBUG'];
const LINE_TERMINATORS = ['\n', '\r', '\u2028', '\u2029'];

function isAsciiDigit(character) {
  return character >= '0' && character <= '9';
}

function isWhitespace(character) {
  return character !== undefined && /\s/u.test(character);
}

function skipWhitespace(value, start) {
  let cursor = start;
  while (cursor < value.length && isWhitespace(value[cursor])) cursor += 1;
  return cursor;
}

function hasLineTerminator(value, start) {
  return LINE_TERMINATORS.some(character => value.indexOf(character, start) >= 0);
}

function parseRawHeader(line) {
  let cursor = 0;
  const takeDigit = () => {
    if (!isAsciiDigit(line[cursor])) return false;
    cursor += 1;
    return true;
  };
  const takeDigits = count => {
    for (let remaining = count; remaining > 0; remaining -= 1) {
      if (!takeDigit()) return false;
    }
    return true;
  };
  const take = character => {
    if (line[cursor] !== character) return false;
    cursor += 1;
    return true;
  };

  if (!takeDigits(2)) return null;
  if (!take('-')) return null;
  if (!takeDigits(2)) return null;
  const dateEnd = cursor;
  cursor = skipWhitespace(line, cursor);
  if (cursor === dateEnd) return null;
  if (!takeDigits(2)) return null;
  if (!take(':')) return null;
  if (!takeDigits(2)) return null;
  if (!take(':')) return null;
  if (!takeDigits(2)) return null;
  const timestampEnd = cursor;
  const levelWhitespace = cursor;
  cursor = skipWhitespace(line, cursor);
  if (cursor === levelWhitespace) return null;

  const level = RAW_LEVELS.find(candidate => line.startsWith(candidate, cursor));
  if (!level) return null;
  cursor += level.length;
  const sourceWhitespace = cursor;
  cursor = skipWhitespace(line, cursor);
  if (cursor === sourceWhitespace || line[cursor] !== '[') return null;

  const sourceStart = cursor + 1;
  const sourceEnd = line.indexOf(']', sourceStart);
  if (sourceEnd < 0) return null;
  cursor = skipWhitespace(line, sourceEnd + 1);
  if (hasLineTerminator(line, cursor)) return null;

  return {
    time: line.slice(0, timestampEnd),
    type: level,
    source: line.slice(sourceStart, sourceEnd).trim(),
    message: line.slice(cursor),
  };
}

function fallbackEntry(line) {
  const levelMatch = line.match(/\b(ERROR|WARNING|INFO|DEBUG)\b/);
  return { time: '', type: levelMatch ? levelMatch[1] : 'INFO', source: '', message: line };
}

export function parseLogLines(lines) {
  if (!Array.isArray(lines)) return [];
  return lines.map(line => {
    if (typeof line === 'object' && line.time) {
      const message = line.message || '';
      const sourceMatch = message.match(/^\[([^\]]*)\]\s*(.*)/);
      return {
        time: line.time,
        type: (line.type || 'INFO').toUpperCase(),
        source: sourceMatch ? sourceMatch[1].trim() : '',
        message: sourceMatch ? sourceMatch[2] : message,
      };
    }
    if (typeof line !== 'string') {
      return { time: '', type: 'INFO', source: '', message: String(line) };
    }
    return parseRawHeader(line) || fallbackEntry(line);
  });
}
