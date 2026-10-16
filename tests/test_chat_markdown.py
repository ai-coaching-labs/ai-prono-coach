"""Rendu Markdown DOM : tableaux lisibles et aucune interprétation de HTML fourni."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'),'Node requis pour le rendu JavaScript')
class ChatMarkdownTests(unittest.TestCase):
    def test_tables_formatting_and_untrusted_markup(self):
        source=(ROOT/'src/prono/assets/chat.js').read_text()
        renderer=source[source.index('function appendMarkdownInline('):source.index('function bubble(')]
        fixture='''## Verdict

| Match | Pronostic | Confiance |
|---|---|---|
| **Rennes** | 1 | faible |
| A\\|B | N | modérée |

- [Source](https://example.test/article)
- <img src=x onerror=alert(1)>

[danger](javascript:alert(1))
<script>alert(1)</script>

```
| texte | brut |
|---|---|
```
'''
        harness=r'''
const assert = require('node:assert/strict');
class Node {
  constructor(tag, data='') { this.tagName=tag; this.data=data; this.children=[]; this.attributes={}; }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(k,v) { this.attributes[k]=v; }
  set textContent(v) { this.data=String(v); this.children=[]; }
  get textContent() { return this.data+this.children.map(n=>n.textContent).join(''); }
  set innerHTML(v) { throw Error('HTML non fiable interprété'); }
}
const document={createElement:tag=>new Node(tag),createTextNode:text=>new Node('#text',text)};
const walk=n=>[n,...n.children.flatMap(walk)];
'''
        assertions=r'''
const body=renderMarkdown(INPUT),nodes=walk(body),all=tag=>nodes.filter(n=>n.tagName===tag);
assert.equal(all('table').length,1);
assert.equal(all('th').length,3);
assert.equal(all('td').length,6);
assert.equal(all('tbody')[0].children.length,2);
assert.equal(all('strong')[0].textContent,'Rennes');
assert.equal(all('td')[3].textContent,'A|B');
assert.equal(all('a').length,1);
assert.equal(all('a')[0].href,'https://example.test/article');
assert.equal(all('a')[0].rel,'noopener noreferrer');
assert.equal(all('img').length,0);assert.equal(all('script').length,0);
assert.ok(body.textContent.includes('<script>alert(1)</script>'));
assert.equal(all('li').length,2);
assert.ok(all('pre')[0].textContent.includes('| texte | brut |'));
assert.equal(all('thead')[0].children[0].children[0].scope,'col');
assert.equal(nodes.find(n=>n.className==='markdown-table-scroll').tabIndex,0);
const code=renderMarkdown('| A | B |\n|---|---|\n| x | `a|b` |');
assert.equal(walk(code).find(n=>n.tagName==='code').textContent,'a|b');
'''
        script=harness+renderer+'\nconst INPUT='+json.dumps(fixture)+';\n'+assertions
        result=subprocess.run([shutil.which('node'),'-e',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
