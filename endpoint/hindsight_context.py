"""Read-only, bounded Hindsight recall over the existing tailnet MCP route.

No bank mutation tools, no memory/transcript logging, no public fallback.
Configuration is supplied by app.py's existing .env loader.
"""
import json
import re
import threading
import time
import urllib.request
from functools import lru_cache

DEFAULT_URL = 'https://kans-water-server.siren-deneb.ts.net/mcp/kan-memory-v2/'


def bounded_number(value, default, lower, upper):
    try:
        number = float(value)
        if not lower <= number <= upper:
            return default
        return number
    except (ValueError, TypeError):
        return default


def extract_terms(text):
    # Candidate spellings only: never promote complete memory sentences to terms.
    return list(dict.fromkeys(re.findall(
        r'[一-龥々]{2,12}|[ァ-ヶー]{2,24}|[A-Za-z][A-Za-z0-9_.+-]{2,30}', text)))


def replacement_only(raw, new, terms):
    """Extra v2 guard: output may only copy original chars or substitute a term.

    Substitutions must consume source characters and cannot span punctuation.
    Existing v1 similarity/length guards are also still applied by app.py.
    """
    if raw == new:
        return True
    if len(raw) > 1500 or len(new) > 1500:
        return False
    candidates = tuple(t for t in dict.fromkeys(terms) if 1 < len(t) <= 64 and t in new)
    punctuation = re.compile(r'[\s、。，．,.!?！？「」【】\[\]]')

    @lru_cache(maxsize=50000)
    def match(i, j):
        if i == len(raw) or j == len(new):
            return i == len(raw) and j == len(new)
        if raw[i] == new[j] and match(i + 1, j + 1):
            return True
        for term in candidates:
            if not new.startswith(term, j):
                continue
            for length in range(1, min(len(raw) - i, len(term) * 2 + 4) + 1):
                source = raw[i:i + length]
                if punctuation.search(source):
                    break
                if match(i + length, j + len(term)):
                    return True
        return False

    try:
        return match(0, 0)
    except RecursionError:
        return False


class RecallClient:
    def __init__(self, env):
        self.enabled = str(env.get('HINDSIGHT_ENABLED', 'false')).lower() in ('1', 'true', 'yes', 'on')
        self.url = env.get('HINDSIGHT_MCP_URL', DEFAULT_URL)
        self.timeout = bounded_number(env.get('HINDSIGHT_TIMEOUT_S'), 4.0, 0.1, 10.0)
        self.max_facts = int(bounded_number(env.get('HINDSIGHT_MAX_FACTS'), 3, 1, 20))
        self.max_chars = int(bounded_number(env.get('HINDSIGHT_MAX_CONTEXT_CHARS'), 1600, 100, 24000))
        self.max_tokens = int(bounded_number(env.get('HINDSIGHT_MAX_TOKENS'), 1200, 100, 6000))
        self.budget = env.get('HINDSIGHT_BUDGET', 'low')
        if self.budget not in ('low', 'mid', 'high'):
            self.budget = 'low'
        self._gate = threading.Lock()
        self._state_lock = threading.Lock()
        self._session = None
        self._protocol = '2024-11-05'
        self._last = {'status': 'not_called', 'elapsed_s': 0, 'facts_count': 0}

    def health(self):
        with self._state_lock:
            last = dict(self._last)
        return {'enabled': self.enabled, 'transport': 'tailnet-mcp', **last}

    def _record(self, result, start):
        result['elapsed_s'] = round(time.monotonic() - start, 3)
        with self._state_lock:
            self._last = {k: result[k] for k in ('status', 'elapsed_s', 'facts_count')}
        return result

    @staticmethod
    def empty(status):
        return {'context': '', 'terms': [], 'status': status, 'facts_count': 0}

    def recall(self, query):
        start = time.monotonic()
        if not self.enabled or not query.strip():
            return self._record(self.empty('disabled' if not self.enabled else 'empty'), start)
        if not self._gate.acquire(blocking=False):
            return self._record(self.empty('busy'), start)
        done = threading.Event()
        box = []
        deadline = start + self.timeout

        def worker():
            try:
                box.append(self._fetch(query[:2000], deadline))
            except Exception:
                # Never expose upstream errors, URLs, source memories, or transcripts.
                self._session = None
                box.append(self.empty('unavailable'))
            finally:
                self._gate.release()
                done.set()

        threading.Thread(target=worker, daemon=True, name='hindsight-recall').start()
        if not done.wait(max(0, deadline - time.monotonic())):
            return self._record(self.empty('timeout'), start)
        return self._record(box[0], start)

    def _rpc(self, method, params, deadline, request_id=1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        # Only the existing tailnet bank route is allowed; never follow redirects.
        if self.url != DEFAULT_URL:
            from urllib.parse import urlsplit
            u = urlsplit(self.url)
            if not (u.scheme == 'https' and u.hostname and u.hostname.endswith('.ts.net')
                    and u.path == '/mcp/kan-memory-v2/' and not u.query and not u.fragment
                    and not u.username and not u.password):
                raise ValueError('tailnet bank route required')
        payload = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if request_id is not None:
            payload['id'] = request_id
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                   'MCP-Protocol-Version': self._protocol}
        if self._session:
            headers['Mcp-Session-Id'] = self._session
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers=headers)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        with urllib.request.build_opener(NoRedirect()).open(req, timeout=remaining) as response:
            session = response.headers.get('Mcp-Session-Id')
            if session:
                self._session = session
            if request_id is None:
                return {}
            # Read only until our response arrives; SSE connections need not close.
            if 'text/event-stream' in response.headers.get('Content-Type', ''):
                data_lines = []
                count = 0
                for line in response:
                    count += len(line)
                    if count > 256000 or time.monotonic() >= deadline:
                        raise TimeoutError()
                    line = line.decode('utf-8').rstrip('\r\n')
                    if line.startswith('data:'):
                        data_lines.append(line[5:].lstrip())
                    elif not line and data_lines:
                        message = json.loads('\n'.join(data_lines)); data_lines = []
                        if message.get('id') == request_id:
                            break
                else:
                    raise ValueError('missing MCP response')
            else:
                body = response.read(256001)
                if len(body) > 256000:
                    raise ValueError('oversize MCP response')
                message = json.loads(body)
            if message.get('error') or message.get('id') != request_id:
                raise ValueError('MCP error')
            return message['result']

    def _fetch(self, query, deadline):
        if not self._session:
            result = self._rpc('initialize', {'protocolVersion': self._protocol, 'capabilities': {},
                'clientInfo': {'name': 'kan-transcribe-endpoint', 'version': '2.0.0'}}, deadline)
            self._protocol = result.get('protocolVersion', self._protocol)
            self._rpc('notifications/initialized', {}, deadline, request_id=None)
        tool = self._rpc('tools/call', {'name': 'recall', 'arguments': {
            'query': query, 'budget': self.budget, 'max_tokens': self.max_tokens}}, deadline, request_id=2)
        if tool.get('isError'):
            raise ValueError('recall failed')
        payload = tool.get('structuredContent')
        if not isinstance(payload, dict) or 'results' not in payload:
            payload = None
            for block in tool.get('content', []):
                if block.get('type') == 'text':
                    parsed = json.loads(block['text'])
                    if isinstance(parsed, dict) and 'results' in parsed:
                        payload = parsed
                        break
        if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
            raise ValueError('invalid recall response')
        facts = []
        for item in payload['results']:
            if not isinstance(item, dict) or not isinstance(item.get('text'), str):
                continue
            text = item['text'].strip()
            if text:
                facts.append(text[:600])
            if len(facts) >= self.max_facts:
                break
        if not facts:
            return self.empty('empty')
        context = '\n'.join(f'- {text}' for text in facts)[:self.max_chars]
        terms = extract_terms(context)[:40]
        return {'context': context, 'terms': terms, 'status': 'ok', 'facts_count': len(facts)}
