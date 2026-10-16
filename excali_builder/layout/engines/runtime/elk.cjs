// JSON in / JSON out. Graph translation belongs to the Python ELK adapter.
const fs = require("node:fs");
const ELK = require("elkjs/lib/elk.bundled.js");
const elk = new ELK();
const input = JSON.parse(fs.readFileSync(0, "utf8"));
elk.layout(input).then(result => {
  process.stdout.write(JSON.stringify(result));
}).catch(error => {
  process.stderr.write(String(error.message || error));
  process.exitCode = 1;
});
