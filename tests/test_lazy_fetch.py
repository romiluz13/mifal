"""The doctor is read-only: with a partial clone as the recorded source, its completeness check must not fetch the
missing trees into the clone's object store; it reports that completeness could not be checked."""

import json
import subprocess
import unittest

import test_update
from support import snapshot


class PartialClone(test_update.Update):
    def setUp(self):
        super().setUp()
        self.git(self.origin, "config", "uploadpack.allowFilter", "true")
        self.git(self.origin, "config", "uploadpack.allowAnySHA1InWant", "true")
        self.partial = self.root / "partial"
        subprocess.run(["git", "clone", "-q", "--filter=tree:0", "--no-checkout", f"file://{self.origin}", str(self.partial)],
                       env=dict(self.env(), GIT_ALLOW_PROTOCOL="file", GIT_CONFIG_NOSYSTEM="1"), check=True,
                       capture_output=True, stdin=subprocess.DEVNULL)
        path = self.home / ".agents/mifal/install-manifest.json"
        data = json.loads(path.read_text())
        data["source"].update(path=str(self.partial), revision=self.head(self.partial))
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        self.installed = snapshot(self.home)

    def objects(self):
        counts = dict(line.split(": ") for line in self.git(self.partial, "count-objects", "-v").splitlines())
        return int(counts["count"]) + int(counts["in-pack"])

    def test_the_doctor_does_not_fetch_into_a_partial_clone_and_says_it_could_not_check(self):
        before = self.objects()
        result = self.mifal("doctor", check=False, GIT_ALLOW_PROTOCOL="file")
        self.assertEqual(self.objects(), before, "the doctor fetched objects into the clone")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"(?m)^WARN engine: completeness could not be checked")
        self.assertEqual(snapshot(self.home), self.installed)


if __name__ == "__main__":
    unittest.main()
