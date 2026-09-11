// JavaScript transforms remain supported at this deliberately small boundary.
// Discovery, scheduling, process lifecycle, and the executable are Rust-owned.
module.exports = require('./rust-compat');
