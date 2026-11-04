#!/usr/bin/env python3
"""Manual generation using exactly the background procedure; never print cache names."""
import json
from pathlib import Path
from dynamic_dictionary import DynamicDictionary

BASE = Path(__file__).resolve().parent

def main():
    env = {}
    for line in (BASE / '.env').read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            env[key.strip()] = value.strip()
    terms = [line.strip() for line in (BASE / 'terms.txt').read_text().splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    cache = DynamicDictionary(BASE, env, terms, env.get('OLLAMA_URL','http://127.0.0.1:11434'),
                              env.get('OLLAMA_MODEL','qwen3.8:27b-mlx'))
    success = cache.refresh()
    print(json.dumps({'success': success, **cache.health()}, ensure_ascii=False))
    raise SystemExit(0 if success else 1)

if __name__ == '__main__': main()
