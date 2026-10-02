import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('gate', HERE/'scripts/security/artifact_gate.py')
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
spec = importlib.util.spec_from_file_location('csp', HERE/'scripts/security/csp.py')
csp = importlib.util.module_from_spec(spec); spec.loader.exec_module(csp)
COMMIT = 'a'*40

class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)/'site'; self.root.mkdir()
        self.root.joinpath('index.html').write_text('<meta http-equiv="Content-Security-Policy" content="'+csp.policy()+'"><script type="module" src="/assets/main.js"></script>')
    def tearDown(self): self.temp.cleanup()
    def test_seal_then_trusted_verify_and_tamper(self):
        receipt = gate.scan(self.root,'berlin',COMMIT)
        expected = Path(self.temp.name)/'receipt.json'; expected.write_text(json.dumps(receipt))
        sha = gate.digest(expected)
        self.assertEqual(gate.verify(self.root,expected,sha,'berlin',COMMIT),receipt)
        self.root.joinpath('extra.txt').write_text('added')
        with self.assertRaises(ValueError): gate.verify(self.root,expected,sha,'berlin',COMMIT)
    def test_detached_digest_and_wrong_city_commit(self):
        expected = Path(self.temp.name)/'receipt.json';expected.write_text(json.dumps(gate.scan(self.root,'berlin',COMMIT)))
        for sha,city,commit in [('b'*64,'berlin',COMMIT),(gate.digest(expected),'essen',COMMIT),(gate.digest(expected),'berlin','b'*40)]:
            with self.assertRaises(ValueError): gate.verify(self.root,expected,sha,city,commit)
    def test_sensitive_files_and_fields(self):
        for name,body in [('police.sqlite',b'x'),('source-review.json',b'{}'),('data.json',b'{"events":[{"article_body":"private"}]}'),('data.txt',b'-----BEGIN PRIVATE KEY-----'),('app.js.map',b'{}')]:
            path=self.root/name;path.write_bytes(body)
            with self.assertRaises(ValueError):gate.scan(self.root,'berlin',COMMIT)
            path.unlink()
    def test_symlink_not_followed(self):
        self.root.joinpath('data.json').symlink_to(self.root/'index.html')
        with self.assertRaises(ValueError):gate.scan(self.root,'berlin',COMMIT)
    def test_current_generation_only(self):
        for gen in ['a'*16+'-20261003T000000','b'*16+'-20261003T000000']:
            p=self.root/'safety'/gen/'search.json';p.parent.mkdir(parents=True);p.write_text('[]')
        with self.assertRaises(ValueError):gate.scan(self.root,'berlin',COMMIT)
    def test_svg_rejects_executable_external_and_entities(self):
        for svg in ['<svg><script>alert(1)</script></svg>','<svg onload="x()"/>','<svg><foreignObject/></svg>','<svg><use href="https://evil/x"/></svg>','<svg><path fill="url(https://evil/x)"/></svg>','<!DOCTYPE svg [<!ENTITY x "x">]><svg/>']:
            with self.assertRaises(ValueError):gate.check_svg(svg.encode())
        gate.check_svg(b'<svg xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g"/></defs><path fill="url(#g)"/><use href="#g"/></svg>')
    def test_missing_csp_and_inline_script(self):
        for page in ['<html/>','<meta http-equiv="Content-Security-Policy" content="script-src *"><script src="https://evil/x.js"></script>','<meta http-equiv="Content-Security-Policy" content="'+csp.policy()+'"><script>alert(1)</script>']:
            self.root.joinpath('index.html').write_text(page)
            with self.assertRaises(ValueError):gate.scan(self.root,'berlin',COMMIT)
    def test_csp_only_exact_origins_and_optional_challenge(self):
        for origin in ['https://*.workers.dev','http://worker.example','https://user@worker.example','https://worker.example/path','https://worker.example:8443','https://worker.example/']:
            with self.assertRaises(ValueError):csp.policy([origin])
        out=csp.policy(['https://feedback.example'],True)
        self.assertIn("script-src 'self' https://challenges.cloudflare.com",out)
        self.assertIn('https://feedback.example',out)
        self.assertNotIn('unsafe-eval',out)
        self.assertIn('https://vector.openstreetmap.org',csp.policy([],False,['https://vector.openstreetmap.org']))
        with self.assertRaises(ValueError):csp.policy([],False,['https://unreviewed.example'])
        csp.apply(self.root/'index.html',['https://feedback.example'],True)
        gate.scan(self.root,'berlin',COMMIT)

if __name__=='__main__': unittest.main()
