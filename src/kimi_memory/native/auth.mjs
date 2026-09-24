import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);
var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __require = /* @__PURE__ */ ((x) => typeof require !== "undefined" ? require : typeof Proxy !== "undefined" ? new Proxy(x, {
  get: (a, b) => (typeof require !== "undefined" ? require : a)[b]
}) : x)(function(x) {
  if (typeof require !== "undefined") return require.apply(this, arguments);
  throw Error('Dynamic require of "' + x + '" is not supported');
});
var __commonJS = (cb, mod) => function __require2() {
  try {
    return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
  } catch (e) {
    throw mod = 0, e;
  }
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));

// node_modules/graceful-fs/polyfills.js
var require_polyfills = __commonJS({
  "node_modules/graceful-fs/polyfills.js"(exports, module) {
    var constants = __require("constants");
    var origCwd = process.cwd;
    var cwd = null;
    var platform = process.env.GRACEFUL_FS_PLATFORM || process.platform;
    process.cwd = function() {
      if (!cwd)
        cwd = origCwd.call(process);
      return cwd;
    };
    try {
      process.cwd();
    } catch (er) {
    }
    if (typeof process.chdir === "function") {
      chdir = process.chdir;
      process.chdir = function(d) {
        cwd = null;
        chdir.call(process, d);
      };
      if (Object.setPrototypeOf) Object.setPrototypeOf(process.chdir, chdir);
    }
    var chdir;
    module.exports = patch;
    function patch(fs) {
      if (constants.hasOwnProperty("O_SYMLINK") && process.version.match(/^v0\.6\.[0-2]|^v0\.5\./)) {
        patchLchmod(fs);
      }
      if (!fs.lutimes) {
        patchLutimes(fs);
      }
      fs.chown = chownFix(fs.chown);
      fs.fchown = chownFix(fs.fchown);
      fs.lchown = chownFix(fs.lchown);
      fs.chmod = chmodFix(fs.chmod);
      fs.fchmod = chmodFix(fs.fchmod);
      fs.lchmod = chmodFix(fs.lchmod);
      fs.chownSync = chownFixSync(fs.chownSync);
      fs.fchownSync = chownFixSync(fs.fchownSync);
      fs.lchownSync = chownFixSync(fs.lchownSync);
      fs.chmodSync = chmodFixSync(fs.chmodSync);
      fs.fchmodSync = chmodFixSync(fs.fchmodSync);
      fs.lchmodSync = chmodFixSync(fs.lchmodSync);
      fs.stat = statFix(fs.stat);
      fs.fstat = statFix(fs.fstat);
      fs.lstat = statFix(fs.lstat);
      fs.statSync = statFixSync(fs.statSync);
      fs.fstatSync = statFixSync(fs.fstatSync);
      fs.lstatSync = statFixSync(fs.lstatSync);
      if (fs.chmod && !fs.lchmod) {
        fs.lchmod = function(path, mode, cb) {
          if (cb) process.nextTick(cb);
        };
        fs.lchmodSync = function() {
        };
      }
      if (fs.chown && !fs.lchown) {
        fs.lchown = function(path, uid, gid, cb) {
          if (cb) process.nextTick(cb);
        };
        fs.lchownSync = function() {
        };
      }
      if (platform === "win32") {
        fs.rename = typeof fs.rename !== "function" ? fs.rename : (function(fs$rename) {
          function rename(from, to, cb) {
            var start = Date.now();
            var backoff = 0;
            fs$rename(from, to, function CB(er) {
              if (er && (er.code === "EACCES" || er.code === "EPERM" || er.code === "EBUSY") && Date.now() - start < 6e4) {
                setTimeout(function() {
                  fs.stat(to, function(stater, st) {
                    if (stater && stater.code === "ENOENT")
                      fs$rename(from, to, CB);
                    else
                      cb(er);
                  });
                }, backoff);
                if (backoff < 100)
                  backoff += 10;
                return;
              }
              if (cb) cb(er);
            });
          }
          if (Object.setPrototypeOf) Object.setPrototypeOf(rename, fs$rename);
          return rename;
        })(fs.rename);
      }
      fs.read = typeof fs.read !== "function" ? fs.read : (function(fs$read) {
        function read(fd, buffer, offset, length, position, callback_) {
          var callback;
          if (callback_ && typeof callback_ === "function") {
            var eagCounter = 0;
            callback = function(er, _, __) {
              if (er && er.code === "EAGAIN" && eagCounter < 10) {
                eagCounter++;
                return fs$read.call(fs, fd, buffer, offset, length, position, callback);
              }
              callback_.apply(this, arguments);
            };
          }
          return fs$read.call(fs, fd, buffer, offset, length, position, callback);
        }
        if (Object.setPrototypeOf) Object.setPrototypeOf(read, fs$read);
        return read;
      })(fs.read);
      fs.readSync = typeof fs.readSync !== "function" ? fs.readSync : /* @__PURE__ */ (function(fs$readSync) {
        return function(fd, buffer, offset, length, position) {
          var eagCounter = 0;
          while (true) {
            try {
              return fs$readSync.call(fs, fd, buffer, offset, length, position);
            } catch (er) {
              if (er.code === "EAGAIN" && eagCounter < 10) {
                eagCounter++;
                continue;
              }
              throw er;
            }
          }
        };
      })(fs.readSync);
      function patchLchmod(fs2) {
        fs2.lchmod = function(path, mode, callback) {
          fs2.open(
            path,
            constants.O_WRONLY | constants.O_SYMLINK,
            mode,
            function(err, fd) {
              if (err) {
                if (callback) callback(err);
                return;
              }
              fs2.fchmod(fd, mode, function(err2) {
                fs2.close(fd, function(err22) {
                  if (callback) callback(err2 || err22);
                });
              });
            }
          );
        };
        fs2.lchmodSync = function(path, mode) {
          var fd = fs2.openSync(path, constants.O_WRONLY | constants.O_SYMLINK, mode);
          var threw = true;
          var ret;
          try {
            ret = fs2.fchmodSync(fd, mode);
            threw = false;
          } finally {
            if (threw) {
              try {
                fs2.closeSync(fd);
              } catch (er) {
              }
            } else {
              fs2.closeSync(fd);
            }
          }
          return ret;
        };
      }
      function patchLutimes(fs2) {
        if (constants.hasOwnProperty("O_SYMLINK") && fs2.futimes) {
          fs2.lutimes = function(path, at, mt, cb) {
            fs2.open(path, constants.O_SYMLINK, function(er, fd) {
              if (er) {
                if (cb) cb(er);
                return;
              }
              fs2.futimes(fd, at, mt, function(er2) {
                fs2.close(fd, function(er22) {
                  if (cb) cb(er2 || er22);
                });
              });
            });
          };
          fs2.lutimesSync = function(path, at, mt) {
            var fd = fs2.openSync(path, constants.O_SYMLINK);
            var ret;
            var threw = true;
            try {
              ret = fs2.futimesSync(fd, at, mt);
              threw = false;
            } finally {
              if (threw) {
                try {
                  fs2.closeSync(fd);
                } catch (er) {
                }
              } else {
                fs2.closeSync(fd);
              }
            }
            return ret;
          };
        } else if (fs2.futimes) {
          fs2.lutimes = function(_a, _b, _c, cb) {
            if (cb) process.nextTick(cb);
          };
          fs2.lutimesSync = function() {
          };
        }
      }
      function chmodFix(orig) {
        if (!orig) return orig;
        return function(target, mode, cb) {
          return orig.call(fs, target, mode, function(er) {
            if (chownErOk(er)) er = null;
            if (cb) cb.apply(this, arguments);
          });
        };
      }
      function chmodFixSync(orig) {
        if (!orig) return orig;
        return function(target, mode) {
          try {
            return orig.call(fs, target, mode);
          } catch (er) {
            if (!chownErOk(er)) throw er;
          }
        };
      }
      function chownFix(orig) {
        if (!orig) return orig;
        return function(target, uid, gid, cb) {
          return orig.call(fs, target, uid, gid, function(er) {
            if (chownErOk(er)) er = null;
            if (cb) cb.apply(this, arguments);
          });
        };
      }
      function chownFixSync(orig) {
        if (!orig) return orig;
        return function(target, uid, gid) {
          try {
            return orig.call(fs, target, uid, gid);
          } catch (er) {
            if (!chownErOk(er)) throw er;
          }
        };
      }
      function statFix(orig) {
        if (!orig) return orig;
        return function(target, options, cb) {
          if (typeof options === "function") {
            cb = options;
            options = null;
          }
          function callback(er, stats) {
            if (stats) {
              if (stats.uid < 0) stats.uid += 4294967296;
              if (stats.gid < 0) stats.gid += 4294967296;
            }
            if (cb) cb.apply(this, arguments);
          }
          return options ? orig.call(fs, target, options, callback) : orig.call(fs, target, callback);
        };
      }
      function statFixSync(orig) {
        if (!orig) return orig;
        return function(target, options) {
          var stats = options ? orig.call(fs, target, options) : orig.call(fs, target);
          if (stats) {
            if (stats.uid < 0) stats.uid += 4294967296;
            if (stats.gid < 0) stats.gid += 4294967296;
          }
          return stats;
        };
      }
      function chownErOk(er) {
        if (!er)
          return true;
        if (er.code === "ENOSYS")
          return true;
        var nonroot = !process.getuid || process.getuid() !== 0;
        if (nonroot) {
          if (er.code === "EINVAL" || er.code === "EPERM")
            return true;
        }
        return false;
      }
    }
  }
});

// node_modules/graceful-fs/legacy-streams.js
var require_legacy_streams = __commonJS({
  "node_modules/graceful-fs/legacy-streams.js"(exports, module) {
    var Stream = __require("stream").Stream;
    module.exports = legacy;
    function legacy(fs) {
      return {
        ReadStream,
        WriteStream
      };
      function ReadStream(path, options) {
        if (!(this instanceof ReadStream)) return new ReadStream(path, options);
        Stream.call(this);
        var self = this;
        this.path = path;
        this.fd = null;
        this.readable = true;
        this.paused = false;
        this.flags = "r";
        this.mode = 438;
        this.bufferSize = 64 * 1024;
        options = options || {};
        var keys = Object.keys(options);
        for (var index = 0, length = keys.length; index < length; index++) {
          var key = keys[index];
          this[key] = options[key];
        }
        if (this.encoding) this.setEncoding(this.encoding);
        if (this.start !== void 0) {
          if ("number" !== typeof this.start) {
            throw TypeError("start must be a Number");
          }
          if (this.end === void 0) {
            this.end = Infinity;
          } else if ("number" !== typeof this.end) {
            throw TypeError("end must be a Number");
          }
          if (this.start > this.end) {
            throw new Error("start must be <= end");
          }
          this.pos = this.start;
        }
        if (this.fd !== null) {
          process.nextTick(function() {
            self._read();
          });
          return;
        }
        fs.open(this.path, this.flags, this.mode, function(err, fd) {
          if (err) {
            self.emit("error", err);
            self.readable = false;
            return;
          }
          self.fd = fd;
          self.emit("open", fd);
          self._read();
        });
      }
      function WriteStream(path, options) {
        if (!(this instanceof WriteStream)) return new WriteStream(path, options);
        Stream.call(this);
        this.path = path;
        this.fd = null;
        this.writable = true;
        this.flags = "w";
        this.encoding = "binary";
        this.mode = 438;
        this.bytesWritten = 0;
        options = options || {};
        var keys = Object.keys(options);
        for (var index = 0, length = keys.length; index < length; index++) {
          var key = keys[index];
          this[key] = options[key];
        }
        if (this.start !== void 0) {
          if ("number" !== typeof this.start) {
            throw TypeError("start must be a Number");
          }
          if (this.start < 0) {
            throw new Error("start must be >= zero");
          }
          this.pos = this.start;
        }
        this.busy = false;
        this._queue = [];
        if (this.fd === null) {
          this._open = fs.open;
          this._queue.push([this._open, this.path, this.flags, this.mode, void 0]);
          this.flush();
        }
      }
    }
  }
});

// node_modules/graceful-fs/clone.js
var require_clone = __commonJS({
  "node_modules/graceful-fs/clone.js"(exports, module) {
    "use strict";
    module.exports = clone;
    var getPrototypeOf = Object.getPrototypeOf || function(obj) {
      return obj.__proto__;
    };
    function clone(obj) {
      if (obj === null || typeof obj !== "object")
        return obj;
      if (obj instanceof Object)
        var copy = { __proto__: getPrototypeOf(obj) };
      else
        var copy = /* @__PURE__ */ Object.create(null);
      Object.getOwnPropertyNames(obj).forEach(function(key) {
        Object.defineProperty(copy, key, Object.getOwnPropertyDescriptor(obj, key));
      });
      return copy;
    }
  }
});

// node_modules/graceful-fs/graceful-fs.js
var require_graceful_fs = __commonJS({
  "node_modules/graceful-fs/graceful-fs.js"(exports, module) {
    var fs = __require("fs");
    var polyfills = require_polyfills();
    var legacy = require_legacy_streams();
    var clone = require_clone();
    var util = __require("util");
    var gracefulQueue;
    var previousSymbol;
    if (typeof Symbol === "function" && typeof Symbol.for === "function") {
      gracefulQueue = /* @__PURE__ */ Symbol.for("graceful-fs.queue");
      previousSymbol = /* @__PURE__ */ Symbol.for("graceful-fs.previous");
    } else {
      gracefulQueue = "___graceful-fs.queue";
      previousSymbol = "___graceful-fs.previous";
    }
    function noop() {
    }
    function publishQueue(context, queue2) {
      Object.defineProperty(context, gracefulQueue, {
        get: function() {
          return queue2;
        }
      });
    }
    var debug = noop;
    if (util.debuglog)
      debug = util.debuglog("gfs4");
    else if (/\bgfs4\b/i.test(process.env.NODE_DEBUG || ""))
      debug = function() {
        var m = util.format.apply(util, arguments);
        m = "GFS4: " + m.split(/\n/).join("\nGFS4: ");
        console.error(m);
      };
    if (!fs[gracefulQueue]) {
      queue = global[gracefulQueue] || [];
      publishQueue(fs, queue);
      fs.close = (function(fs$close) {
        function close(fd, cb) {
          return fs$close.call(fs, fd, function(err) {
            if (!err) {
              resetQueue();
            }
            if (typeof cb === "function")
              cb.apply(this, arguments);
          });
        }
        Object.defineProperty(close, previousSymbol, {
          value: fs$close
        });
        return close;
      })(fs.close);
      fs.closeSync = (function(fs$closeSync) {
        function closeSync2(fd) {
          fs$closeSync.apply(fs, arguments);
          resetQueue();
        }
        Object.defineProperty(closeSync2, previousSymbol, {
          value: fs$closeSync
        });
        return closeSync2;
      })(fs.closeSync);
      if (/\bgfs4\b/i.test(process.env.NODE_DEBUG || "")) {
        process.on("exit", function() {
          debug(fs[gracefulQueue]);
          __require("assert").equal(fs[gracefulQueue].length, 0);
        });
      }
    }
    var queue;
    if (!global[gracefulQueue]) {
      publishQueue(global, fs[gracefulQueue]);
    }
    module.exports = patch(clone(fs));
    if (process.env.TEST_GRACEFUL_FS_GLOBAL_PATCH && !fs.__patched) {
      module.exports = patch(fs);
      fs.__patched = true;
    }
    function patch(fs2) {
      polyfills(fs2);
      fs2.gracefulify = patch;
      fs2.createReadStream = createReadStream;
      fs2.createWriteStream = createWriteStream;
      var fs$readFile = fs2.readFile;
      fs2.readFile = readFile;
      function readFile(path, options, cb) {
        if (typeof options === "function")
          cb = options, options = null;
        return go$readFile(path, options, cb);
        function go$readFile(path2, options2, cb2, startTime) {
          return fs$readFile(path2, options2, function(err) {
            if (err && (err.code === "EMFILE" || err.code === "ENFILE"))
              enqueue([go$readFile, [path2, options2, cb2], err, startTime || Date.now(), Date.now()]);
            else {
              if (typeof cb2 === "function")
                cb2.apply(this, arguments);
            }
          });
        }
      }
      var fs$writeFile = fs2.writeFile;
      fs2.writeFile = writeFile2;
      function writeFile2(path, data, options, cb) {
        if (typeof options === "function")
          cb = options, options = null;
        return go$writeFile(path, data, options, cb);
        function go$writeFile(path2, data2, options2, cb2, startTime) {
          return fs$writeFile(path2, data2, options2, function(err) {
            if (err && (err.code === "EMFILE" || err.code === "ENFILE"))
              enqueue([go$writeFile, [path2, data2, options2, cb2], err, startTime || Date.now(), Date.now()]);
            else {
              if (typeof cb2 === "function")
                cb2.apply(this, arguments);
            }
          });
        }
      }
      var fs$appendFile = fs2.appendFile;
      if (fs$appendFile)
        fs2.appendFile = appendFile;
      function appendFile(path, data, options, cb) {
        if (typeof options === "function")
          cb = options, options = null;
        return go$appendFile(path, data, options, cb);
        function go$appendFile(path2, data2, options2, cb2, startTime) {
          return fs$appendFile(path2, data2, options2, function(err) {
            if (err && (err.code === "EMFILE" || err.code === "ENFILE"))
              enqueue([go$appendFile, [path2, data2, options2, cb2], err, startTime || Date.now(), Date.now()]);
            else {
              if (typeof cb2 === "function")
                cb2.apply(this, arguments);
            }
          });
        }
      }
      var fs$copyFile = fs2.copyFile;
      if (fs$copyFile)
        fs2.copyFile = copyFile;
      function copyFile(src, dest, flags, cb) {
        if (typeof flags === "function") {
          cb = flags;
          flags = 0;
        }
        return go$copyFile(src, dest, flags, cb);
        function go$copyFile(src2, dest2, flags2, cb2, startTime) {
          return fs$copyFile(src2, dest2, flags2, function(err) {
            if (err && (err.code === "EMFILE" || err.code === "ENFILE"))
              enqueue([go$copyFile, [src2, dest2, flags2, cb2], err, startTime || Date.now(), Date.now()]);
            else {
              if (typeof cb2 === "function")
                cb2.apply(this, arguments);
            }
          });
        }
      }
      var fs$readdir = fs2.readdir;
      fs2.readdir = readdir;
      var noReaddirOptionVersions = /^v[0-5]\./;
      function readdir(path, options, cb) {
        if (typeof options === "function")
          cb = options, options = null;
        var go$readdir = noReaddirOptionVersions.test(process.version) ? function go$readdir2(path2, options2, cb2, startTime) {
          return fs$readdir(path2, fs$readdirCallback(
            path2,
            options2,
            cb2,
            startTime
          ));
        } : function go$readdir2(path2, options2, cb2, startTime) {
          return fs$readdir(path2, options2, fs$readdirCallback(
            path2,
            options2,
            cb2,
            startTime
          ));
        };
        return go$readdir(path, options, cb);
        function fs$readdirCallback(path2, options2, cb2, startTime) {
          return function(err, files) {
            if (err && (err.code === "EMFILE" || err.code === "ENFILE"))
              enqueue([
                go$readdir,
                [path2, options2, cb2],
                err,
                startTime || Date.now(),
                Date.now()
              ]);
            else {
              if (files && files.sort)
                files.sort();
              if (typeof cb2 === "function")
                cb2.call(this, err, files);
            }
          };
        }
      }
      if (process.version.substr(0, 4) === "v0.8") {
        var legStreams = legacy(fs2);
        ReadStream = legStreams.ReadStream;
        WriteStream = legStreams.WriteStream;
      }
      var fs$ReadStream = fs2.ReadStream;
      if (fs$ReadStream) {
        ReadStream.prototype = Object.create(fs$ReadStream.prototype);
        ReadStream.prototype.open = ReadStream$open;
      }
      var fs$WriteStream = fs2.WriteStream;
      if (fs$WriteStream) {
        WriteStream.prototype = Object.create(fs$WriteStream.prototype);
        WriteStream.prototype.open = WriteStream$open;
      }
      Object.defineProperty(fs2, "ReadStream", {
        get: function() {
          return ReadStream;
        },
        set: function(val) {
          ReadStream = val;
        },
        enumerable: true,
        configurable: true
      });
      Object.defineProperty(fs2, "WriteStream", {
        get: function() {
          return WriteStream;
        },
        set: function(val) {
          WriteStream = val;
        },
        enumerable: true,
        configurable: true
      });
      var FileReadStream = ReadStream;
      Object.defineProperty(fs2, "FileReadStream", {
        get: function() {
          return FileReadStream;
        },
        set: function(val) {
          FileReadStream = val;
        },
        enumerable: true,
        configurable: true
      });
      var FileWriteStream = WriteStream;
      Object.defineProperty(fs2, "FileWriteStream", {
        get: function() {
          return FileWriteStream;
        },
        set: function(val) {
          FileWriteStream = val;
        },
        enumerable: true,
        configurable: true
      });
      function ReadStream(path, options) {
        if (this instanceof ReadStream)
          return fs$ReadStream.apply(this, arguments), this;
        else
          return ReadStream.apply(Object.create(ReadStream.prototype), arguments);
      }
      function ReadStream$open() {
        var that = this;
        open(that.path, that.flags, that.mode, function(err, fd) {
          if (err) {
            if (that.autoClose)
              that.destroy();
            that.emit("error", err);
          } else {
            that.fd = fd;
            that.emit("open", fd);
            that.read();
          }
        });
      }
      function WriteStream(path, options) {
        if (this instanceof WriteStream)
          return fs$WriteStream.apply(this, arguments), this;
        else
          return WriteStream.apply(Object.create(WriteStream.prototype), arguments);
      }
      function WriteStream$open() {
        var that = this;
        open(that.path, that.flags, that.mode, function(err, fd) {
          if (err) {
            that.destroy();
            that.emit("error", err);
          } else {
            that.fd = fd;
            that.emit("open", fd);
          }
        });
      }
      function createReadStream(path, options) {
        return new fs2.ReadStream(path, options);
      }
      function createWriteStream(path, options) {
        return new fs2.WriteStream(path, options);
      }
      var fs$open = fs2.open;
      fs2.open = open;
      function open(path, flags, mode, cb) {
        if (typeof mode === "function")
          cb = mode, mode = null;
        return go$open(path, flags, mode, cb);
        function go$open(path2, flags2, mode2, cb2, startTime) {
          return fs$open(path2, flags2, mode2, function(err, fd) {
            if (err && (err.code === "EMFILE" || err.code === "ENFILE"))
              enqueue([go$open, [path2, flags2, mode2, cb2], err, startTime || Date.now(), Date.now()]);
            else {
              if (typeof cb2 === "function")
                cb2.apply(this, arguments);
            }
          });
        }
      }
      return fs2;
    }
    function enqueue(elem) {
      debug("ENQUEUE", elem[0].name, elem[1]);
      fs[gracefulQueue].push(elem);
      retry();
    }
    var retryTimer;
    function resetQueue() {
      var now = Date.now();
      for (var i = 0; i < fs[gracefulQueue].length; ++i) {
        if (fs[gracefulQueue][i].length > 2) {
          fs[gracefulQueue][i][3] = now;
          fs[gracefulQueue][i][4] = now;
        }
      }
      retry();
    }
    function retry() {
      clearTimeout(retryTimer);
      retryTimer = void 0;
      if (fs[gracefulQueue].length === 0)
        return;
      var elem = fs[gracefulQueue].shift();
      var fn = elem[0];
      var args = elem[1];
      var err = elem[2];
      var startTime = elem[3];
      var lastTime = elem[4];
      if (startTime === void 0) {
        debug("RETRY", fn.name, args);
        fn.apply(null, args);
      } else if (Date.now() - startTime >= 6e4) {
        debug("TIMEOUT", fn.name, args);
        var cb = args.pop();
        if (typeof cb === "function")
          cb.call(null, err);
      } else {
        var sinceAttempt = Date.now() - lastTime;
        var sinceStart = Math.max(lastTime - startTime, 1);
        var desiredDelay = Math.min(sinceStart * 1.2, 100);
        if (sinceAttempt >= desiredDelay) {
          debug("RETRY", fn.name, args);
          fn.apply(null, args.concat([startTime]));
        } else {
          fs[gracefulQueue].push(elem);
        }
      }
      if (retryTimer === void 0) {
        retryTimer = setTimeout(retry, 0);
      }
    }
  }
});

// node_modules/retry/lib/retry_operation.js
var require_retry_operation = __commonJS({
  "node_modules/retry/lib/retry_operation.js"(exports, module) {
    function RetryOperation(timeouts, options) {
      if (typeof options === "boolean") {
        options = { forever: options };
      }
      this._originalTimeouts = JSON.parse(JSON.stringify(timeouts));
      this._timeouts = timeouts;
      this._options = options || {};
      this._maxRetryTime = options && options.maxRetryTime || Infinity;
      this._fn = null;
      this._errors = [];
      this._attempts = 1;
      this._operationTimeout = null;
      this._operationTimeoutCb = null;
      this._timeout = null;
      this._operationStart = null;
      if (this._options.forever) {
        this._cachedTimeouts = this._timeouts.slice(0);
      }
    }
    module.exports = RetryOperation;
    RetryOperation.prototype.reset = function() {
      this._attempts = 1;
      this._timeouts = this._originalTimeouts;
    };
    RetryOperation.prototype.stop = function() {
      if (this._timeout) {
        clearTimeout(this._timeout);
      }
      this._timeouts = [];
      this._cachedTimeouts = null;
    };
    RetryOperation.prototype.retry = function(err) {
      if (this._timeout) {
        clearTimeout(this._timeout);
      }
      if (!err) {
        return false;
      }
      var currentTime = (/* @__PURE__ */ new Date()).getTime();
      if (err && currentTime - this._operationStart >= this._maxRetryTime) {
        this._errors.unshift(new Error("RetryOperation timeout occurred"));
        return false;
      }
      this._errors.push(err);
      var timeout = this._timeouts.shift();
      if (timeout === void 0) {
        if (this._cachedTimeouts) {
          this._errors.splice(this._errors.length - 1, this._errors.length);
          this._timeouts = this._cachedTimeouts.slice(0);
          timeout = this._timeouts.shift();
        } else {
          return false;
        }
      }
      var self = this;
      var timer = setTimeout(function() {
        self._attempts++;
        if (self._operationTimeoutCb) {
          self._timeout = setTimeout(function() {
            self._operationTimeoutCb(self._attempts);
          }, self._operationTimeout);
          if (self._options.unref) {
            self._timeout.unref();
          }
        }
        self._fn(self._attempts);
      }, timeout);
      if (this._options.unref) {
        timer.unref();
      }
      return true;
    };
    RetryOperation.prototype.attempt = function(fn, timeoutOps) {
      this._fn = fn;
      if (timeoutOps) {
        if (timeoutOps.timeout) {
          this._operationTimeout = timeoutOps.timeout;
        }
        if (timeoutOps.cb) {
          this._operationTimeoutCb = timeoutOps.cb;
        }
      }
      var self = this;
      if (this._operationTimeoutCb) {
        this._timeout = setTimeout(function() {
          self._operationTimeoutCb();
        }, self._operationTimeout);
      }
      this._operationStart = (/* @__PURE__ */ new Date()).getTime();
      this._fn(this._attempts);
    };
    RetryOperation.prototype.try = function(fn) {
      console.log("Using RetryOperation.try() is deprecated");
      this.attempt(fn);
    };
    RetryOperation.prototype.start = function(fn) {
      console.log("Using RetryOperation.start() is deprecated");
      this.attempt(fn);
    };
    RetryOperation.prototype.start = RetryOperation.prototype.try;
    RetryOperation.prototype.errors = function() {
      return this._errors;
    };
    RetryOperation.prototype.attempts = function() {
      return this._attempts;
    };
    RetryOperation.prototype.mainError = function() {
      if (this._errors.length === 0) {
        return null;
      }
      var counts = {};
      var mainError = null;
      var mainErrorCount = 0;
      for (var i = 0; i < this._errors.length; i++) {
        var error = this._errors[i];
        var message = error.message;
        var count = (counts[message] || 0) + 1;
        counts[message] = count;
        if (count >= mainErrorCount) {
          mainError = error;
          mainErrorCount = count;
        }
      }
      return mainError;
    };
  }
});

// node_modules/retry/lib/retry.js
var require_retry = __commonJS({
  "node_modules/retry/lib/retry.js"(exports) {
    var RetryOperation = require_retry_operation();
    exports.operation = function(options) {
      var timeouts = exports.timeouts(options);
      return new RetryOperation(timeouts, {
        forever: options && options.forever,
        unref: options && options.unref,
        maxRetryTime: options && options.maxRetryTime
      });
    };
    exports.timeouts = function(options) {
      if (options instanceof Array) {
        return [].concat(options);
      }
      var opts = {
        retries: 10,
        factor: 2,
        minTimeout: 1 * 1e3,
        maxTimeout: Infinity,
        randomize: false
      };
      for (var key in options) {
        opts[key] = options[key];
      }
      if (opts.minTimeout > opts.maxTimeout) {
        throw new Error("minTimeout is greater than maxTimeout");
      }
      var timeouts = [];
      for (var i = 0; i < opts.retries; i++) {
        timeouts.push(this.createTimeout(i, opts));
      }
      if (options && options.forever && !timeouts.length) {
        timeouts.push(this.createTimeout(i, opts));
      }
      timeouts.sort(function(a, b) {
        return a - b;
      });
      return timeouts;
    };
    exports.createTimeout = function(attempt, opts) {
      var random = opts.randomize ? Math.random() + 1 : 1;
      var timeout = Math.round(random * opts.minTimeout * Math.pow(opts.factor, attempt));
      timeout = Math.min(timeout, opts.maxTimeout);
      return timeout;
    };
    exports.wrap = function(obj, options, methods) {
      if (options instanceof Array) {
        methods = options;
        options = null;
      }
      if (!methods) {
        methods = [];
        for (var key in obj) {
          if (typeof obj[key] === "function") {
            methods.push(key);
          }
        }
      }
      for (var i = 0; i < methods.length; i++) {
        var method = methods[i];
        var original = obj[method];
        obj[method] = function retryWrapper(original2) {
          var op = exports.operation(options);
          var args = Array.prototype.slice.call(arguments, 1);
          var callback = args.pop();
          args.push(function(err) {
            if (op.retry(err)) {
              return;
            }
            if (err) {
              arguments[0] = op.mainError();
            }
            callback.apply(this, arguments);
          });
          op.attempt(function() {
            original2.apply(obj, args);
          });
        }.bind(obj, original);
        obj[method].options = options;
      }
    };
  }
});

// node_modules/retry/index.js
var require_retry2 = __commonJS({
  "node_modules/retry/index.js"(exports, module) {
    module.exports = require_retry();
  }
});

// node_modules/signal-exit/signals.js
var require_signals = __commonJS({
  "node_modules/signal-exit/signals.js"(exports, module) {
    module.exports = [
      "SIGABRT",
      "SIGALRM",
      "SIGHUP",
      "SIGINT",
      "SIGTERM"
    ];
    if (process.platform !== "win32") {
      module.exports.push(
        "SIGVTALRM",
        "SIGXCPU",
        "SIGXFSZ",
        "SIGUSR2",
        "SIGTRAP",
        "SIGSYS",
        "SIGQUIT",
        "SIGIOT"
        // should detect profiler and enable/disable accordingly.
        // see #21
        // 'SIGPROF'
      );
    }
    if (process.platform === "linux") {
      module.exports.push(
        "SIGIO",
        "SIGPOLL",
        "SIGPWR",
        "SIGSTKFLT",
        "SIGUNUSED"
      );
    }
  }
});

// node_modules/signal-exit/index.js
var require_signal_exit = __commonJS({
  "node_modules/signal-exit/index.js"(exports, module) {
    var process2 = global.process;
    var processOk = function(process3) {
      return process3 && typeof process3 === "object" && typeof process3.removeListener === "function" && typeof process3.emit === "function" && typeof process3.reallyExit === "function" && typeof process3.listeners === "function" && typeof process3.kill === "function" && typeof process3.pid === "number" && typeof process3.on === "function";
    };
    if (!processOk(process2)) {
      module.exports = function() {
        return function() {
        };
      };
    } else {
      assert = __require("assert");
      signals = require_signals();
      isWin = /^win/i.test(process2.platform);
      EE = __require("events");
      if (typeof EE !== "function") {
        EE = EE.EventEmitter;
      }
      if (process2.__signal_exit_emitter__) {
        emitter = process2.__signal_exit_emitter__;
      } else {
        emitter = process2.__signal_exit_emitter__ = new EE();
        emitter.count = 0;
        emitter.emitted = {};
      }
      if (!emitter.infinite) {
        emitter.setMaxListeners(Infinity);
        emitter.infinite = true;
      }
      module.exports = function(cb, opts) {
        if (!processOk(global.process)) {
          return function() {
          };
        }
        assert.equal(typeof cb, "function", "a callback must be provided for exit handler");
        if (loaded === false) {
          load();
        }
        var ev = "exit";
        if (opts && opts.alwaysLast) {
          ev = "afterexit";
        }
        var remove = function() {
          emitter.removeListener(ev, cb);
          if (emitter.listeners("exit").length === 0 && emitter.listeners("afterexit").length === 0) {
            unload();
          }
        };
        emitter.on(ev, cb);
        return remove;
      };
      unload = function unload2() {
        if (!loaded || !processOk(global.process)) {
          return;
        }
        loaded = false;
        signals.forEach(function(sig) {
          try {
            process2.removeListener(sig, sigListeners[sig]);
          } catch (er) {
          }
        });
        process2.emit = originalProcessEmit;
        process2.reallyExit = originalProcessReallyExit;
        emitter.count -= 1;
      };
      module.exports.unload = unload;
      emit = function emit2(event, code, signal) {
        if (emitter.emitted[event]) {
          return;
        }
        emitter.emitted[event] = true;
        emitter.emit(event, code, signal);
      };
      sigListeners = {};
      signals.forEach(function(sig) {
        sigListeners[sig] = function listener() {
          if (!processOk(global.process)) {
            return;
          }
          var listeners = process2.listeners(sig);
          if (listeners.length === emitter.count) {
            unload();
            emit("exit", null, sig);
            emit("afterexit", null, sig);
            if (isWin && sig === "SIGHUP") {
              sig = "SIGINT";
            }
            process2.kill(process2.pid, sig);
          }
        };
      });
      module.exports.signals = function() {
        return signals;
      };
      loaded = false;
      load = function load2() {
        if (loaded || !processOk(global.process)) {
          return;
        }
        loaded = true;
        emitter.count += 1;
        signals = signals.filter(function(sig) {
          try {
            process2.on(sig, sigListeners[sig]);
            return true;
          } catch (er) {
            return false;
          }
        });
        process2.emit = processEmit;
        process2.reallyExit = processReallyExit;
      };
      module.exports.load = load;
      originalProcessReallyExit = process2.reallyExit;
      processReallyExit = function processReallyExit2(code) {
        if (!processOk(global.process)) {
          return;
        }
        process2.exitCode = code || /* istanbul ignore next */
        0;
        emit("exit", process2.exitCode, null);
        emit("afterexit", process2.exitCode, null);
        originalProcessReallyExit.call(process2, process2.exitCode);
      };
      originalProcessEmit = process2.emit;
      processEmit = function processEmit2(ev, arg) {
        if (ev === "exit" && processOk(global.process)) {
          if (arg !== void 0) {
            process2.exitCode = arg;
          }
          var ret = originalProcessEmit.apply(this, arguments);
          emit("exit", process2.exitCode, null);
          emit("afterexit", process2.exitCode, null);
          return ret;
        } else {
          return originalProcessEmit.apply(this, arguments);
        }
      };
    }
    var assert;
    var signals;
    var isWin;
    var EE;
    var emitter;
    var unload;
    var emit;
    var sigListeners;
    var loaded;
    var load;
    var originalProcessReallyExit;
    var processReallyExit;
    var originalProcessEmit;
    var processEmit;
  }
});

// node_modules/proper-lockfile/lib/mtime-precision.js
var require_mtime_precision = __commonJS({
  "node_modules/proper-lockfile/lib/mtime-precision.js"(exports, module) {
    "use strict";
    var cacheSymbol = /* @__PURE__ */ Symbol();
    function probe(file, fs, callback) {
      const cachedPrecision = fs[cacheSymbol];
      if (cachedPrecision) {
        return fs.stat(file, (err, stat) => {
          if (err) {
            return callback(err);
          }
          callback(null, stat.mtime, cachedPrecision);
        });
      }
      const mtime = new Date(Math.ceil(Date.now() / 1e3) * 1e3 + 5);
      fs.utimes(file, mtime, mtime, (err) => {
        if (err) {
          return callback(err);
        }
        fs.stat(file, (err2, stat) => {
          if (err2) {
            return callback(err2);
          }
          const precision = stat.mtime.getTime() % 1e3 === 0 ? "s" : "ms";
          Object.defineProperty(fs, cacheSymbol, { value: precision });
          callback(null, stat.mtime, precision);
        });
      });
    }
    function getMtime(precision) {
      let now = Date.now();
      if (precision === "s") {
        now = Math.ceil(now / 1e3) * 1e3;
      }
      return new Date(now);
    }
    module.exports.probe = probe;
    module.exports.getMtime = getMtime;
  }
});

// node_modules/proper-lockfile/lib/lockfile.js
var require_lockfile = __commonJS({
  "node_modules/proper-lockfile/lib/lockfile.js"(exports, module) {
    "use strict";
    var path = __require("path");
    var fs = require_graceful_fs();
    var retry = require_retry2();
    var onExit = require_signal_exit();
    var mtimePrecision = require_mtime_precision();
    var locks = {};
    function getLockFile(file, options) {
      return options.lockfilePath || `${file}.lock`;
    }
    function resolveCanonicalPath(file, options, callback) {
      if (!options.realpath) {
        return callback(null, path.resolve(file));
      }
      options.fs.realpath(file, callback);
    }
    function acquireLock(file, options, callback) {
      const lockfilePath = getLockFile(file, options);
      options.fs.mkdir(lockfilePath, (err) => {
        if (!err) {
          return mtimePrecision.probe(lockfilePath, options.fs, (err2, mtime, mtimePrecision2) => {
            if (err2) {
              options.fs.rmdir(lockfilePath, () => {
              });
              return callback(err2);
            }
            callback(null, mtime, mtimePrecision2);
          });
        }
        if (err.code !== "EEXIST") {
          return callback(err);
        }
        if (options.stale <= 0) {
          return callback(Object.assign(new Error("Lock file is already being held"), { code: "ELOCKED", file }));
        }
        options.fs.stat(lockfilePath, (err2, stat) => {
          if (err2) {
            if (err2.code === "ENOENT") {
              return acquireLock(file, { ...options, stale: 0 }, callback);
            }
            return callback(err2);
          }
          if (!isLockStale(stat, options)) {
            return callback(Object.assign(new Error("Lock file is already being held"), { code: "ELOCKED", file }));
          }
          removeLock(file, options, (err3) => {
            if (err3) {
              return callback(err3);
            }
            acquireLock(file, { ...options, stale: 0 }, callback);
          });
        });
      });
    }
    function isLockStale(stat, options) {
      return stat.mtime.getTime() < Date.now() - options.stale;
    }
    function removeLock(file, options, callback) {
      options.fs.rmdir(getLockFile(file, options), (err) => {
        if (err && err.code !== "ENOENT") {
          return callback(err);
        }
        callback();
      });
    }
    function updateLock(file, options) {
      const lock2 = locks[file];
      if (lock2.updateTimeout) {
        return;
      }
      lock2.updateDelay = lock2.updateDelay || options.update;
      lock2.updateTimeout = setTimeout(() => {
        lock2.updateTimeout = null;
        options.fs.stat(lock2.lockfilePath, (err, stat) => {
          const isOverThreshold = lock2.lastUpdate + options.stale < Date.now();
          if (err) {
            if (err.code === "ENOENT" || isOverThreshold) {
              return setLockAsCompromised(file, lock2, Object.assign(err, { code: "ECOMPROMISED" }));
            }
            lock2.updateDelay = 1e3;
            return updateLock(file, options);
          }
          const isMtimeOurs = lock2.mtime.getTime() === stat.mtime.getTime();
          if (!isMtimeOurs) {
            return setLockAsCompromised(
              file,
              lock2,
              Object.assign(
                new Error("Unable to update lock within the stale threshold"),
                { code: "ECOMPROMISED" }
              )
            );
          }
          const mtime = mtimePrecision.getMtime(lock2.mtimePrecision);
          options.fs.utimes(lock2.lockfilePath, mtime, mtime, (err2) => {
            const isOverThreshold2 = lock2.lastUpdate + options.stale < Date.now();
            if (lock2.released) {
              return;
            }
            if (err2) {
              if (err2.code === "ENOENT" || isOverThreshold2) {
                return setLockAsCompromised(file, lock2, Object.assign(err2, { code: "ECOMPROMISED" }));
              }
              lock2.updateDelay = 1e3;
              return updateLock(file, options);
            }
            lock2.mtime = mtime;
            lock2.lastUpdate = Date.now();
            lock2.updateDelay = null;
            updateLock(file, options);
          });
        });
      }, lock2.updateDelay);
      if (lock2.updateTimeout.unref) {
        lock2.updateTimeout.unref();
      }
    }
    function setLockAsCompromised(file, lock2, err) {
      lock2.released = true;
      if (lock2.updateTimeout) {
        clearTimeout(lock2.updateTimeout);
      }
      if (locks[file] === lock2) {
        delete locks[file];
      }
      lock2.options.onCompromised(err);
    }
    function lock(file, options, callback) {
      options = {
        stale: 1e4,
        update: null,
        realpath: true,
        retries: 0,
        fs,
        onCompromised: (err) => {
          throw err;
        },
        ...options
      };
      options.retries = options.retries || 0;
      options.retries = typeof options.retries === "number" ? { retries: options.retries } : options.retries;
      options.stale = Math.max(options.stale || 0, 2e3);
      options.update = options.update == null ? options.stale / 2 : options.update || 0;
      options.update = Math.max(Math.min(options.update, options.stale / 2), 1e3);
      resolveCanonicalPath(file, options, (err, file2) => {
        if (err) {
          return callback(err);
        }
        const operation = retry.operation(options.retries);
        operation.attempt(() => {
          acquireLock(file2, options, (err2, mtime, mtimePrecision2) => {
            if (operation.retry(err2)) {
              return;
            }
            if (err2) {
              return callback(operation.mainError());
            }
            const lock2 = locks[file2] = {
              lockfilePath: getLockFile(file2, options),
              mtime,
              mtimePrecision: mtimePrecision2,
              options,
              lastUpdate: Date.now()
            };
            updateLock(file2, options);
            callback(null, (releasedCallback) => {
              if (lock2.released) {
                return releasedCallback && releasedCallback(Object.assign(new Error("Lock is already released"), { code: "ERELEASED" }));
              }
              unlock(file2, { ...options, realpath: false }, releasedCallback);
            });
          });
        });
      });
    }
    function unlock(file, options, callback) {
      options = {
        fs,
        realpath: true,
        ...options
      };
      resolveCanonicalPath(file, options, (err, file2) => {
        if (err) {
          return callback(err);
        }
        const lock2 = locks[file2];
        if (!lock2) {
          return callback(Object.assign(new Error("Lock is not acquired/owned by you"), { code: "ENOTACQUIRED" }));
        }
        lock2.updateTimeout && clearTimeout(lock2.updateTimeout);
        lock2.released = true;
        delete locks[file2];
        removeLock(file2, options, callback);
      });
    }
    function check(file, options, callback) {
      options = {
        stale: 1e4,
        realpath: true,
        fs,
        ...options
      };
      options.stale = Math.max(options.stale || 0, 2e3);
      resolveCanonicalPath(file, options, (err, file2) => {
        if (err) {
          return callback(err);
        }
        options.fs.stat(getLockFile(file2, options), (err2, stat) => {
          if (err2) {
            return err2.code === "ENOENT" ? callback(null, false) : callback(err2);
          }
          return callback(null, !isLockStale(stat, options));
        });
      });
    }
    function getLocks() {
      return locks;
    }
    onExit(() => {
      for (const file in locks) {
        const options = locks[file].options;
        try {
          options.fs.rmdirSync(getLockFile(file, options));
        } catch (e) {
        }
      }
    });
    module.exports.lock = lock;
    module.exports.unlock = unlock;
    module.exports.check = check;
    module.exports.getLocks = getLocks;
  }
});

// node_modules/proper-lockfile/lib/adapter.js
var require_adapter = __commonJS({
  "node_modules/proper-lockfile/lib/adapter.js"(exports, module) {
    "use strict";
    var fs = require_graceful_fs();
    function createSyncFs(fs2) {
      const methods = ["mkdir", "realpath", "stat", "rmdir", "utimes"];
      const newFs = { ...fs2 };
      methods.forEach((method) => {
        newFs[method] = (...args) => {
          const callback = args.pop();
          let ret;
          try {
            ret = fs2[`${method}Sync`](...args);
          } catch (err) {
            return callback(err);
          }
          callback(null, ret);
        };
      });
      return newFs;
    }
    function toPromise(method) {
      return (...args) => new Promise((resolve2, reject) => {
        args.push((err, result) => {
          if (err) {
            reject(err);
          } else {
            resolve2(result);
          }
        });
        method(...args);
      });
    }
    function toSync(method) {
      return (...args) => {
        let err;
        let result;
        args.push((_err, _result) => {
          err = _err;
          result = _result;
        });
        method(...args);
        if (err) {
          throw err;
        }
        return result;
      };
    }
    function toSyncOptions(options) {
      options = { ...options };
      options.fs = createSyncFs(options.fs || fs);
      if (typeof options.retries === "number" && options.retries > 0 || options.retries && typeof options.retries.retries === "number" && options.retries.retries > 0) {
        throw Object.assign(new Error("Cannot use retries with the sync api"), { code: "ESYNC" });
      }
      return options;
    }
    module.exports = {
      toPromise,
      toSync,
      toSyncOptions
    };
  }
});

// node_modules/proper-lockfile/index.js
var require_proper_lockfile = __commonJS({
  "node_modules/proper-lockfile/index.js"(exports, module) {
    "use strict";
    var lockfile2 = require_lockfile();
    var { toPromise, toSync, toSyncOptions } = require_adapter();
    async function lock(file, options) {
      const release2 = await toPromise(lockfile2.lock)(file, options);
      return toPromise(release2);
    }
    function lockSync(file, options) {
      const release2 = toSync(lockfile2.lock)(file, toSyncOptions(options));
      return toSync(release2);
    }
    function unlock(file, options) {
      return toPromise(lockfile2.unlock)(file, options);
    }
    function unlockSync(file, options) {
      return toSync(lockfile2.unlock)(file, toSyncOptions(options));
    }
    function check(file, options) {
      return toPromise(lockfile2.check)(file, options);
    }
    function checkSync(file, options) {
      return toSync(lockfile2.check)(file, toSyncOptions(options));
    }
    module.exports = lock;
    module.exports.lock = lock;
    module.exports.unlock = unlock;
    module.exports.lockSync = lockSync;
    module.exports.unlockSync = unlockSync;
    module.exports.check = check;
    module.exports.checkSync = checkSync;
  }
});

// bridge/auth.ts
import { join as join3, resolve } from "node:path";

// vendor/kimi-oauth/oauth-manager.ts
var import_proper_lockfile = __toESM(require_proper_lockfile());
import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

// vendor/kimi-oauth/errors.ts
var OAuthError = class extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = "OAuthError";
  }
};
var OAuthUnauthorizedError = class extends OAuthError {
  constructor(message) {
    super(message);
    this.name = "OAuthUnauthorizedError";
  }
};
var OAuthAccessDeniedError = class extends OAuthError {
  constructor(message = "Authorization denied.") {
    super(message);
    this.name = "OAuthAccessDeniedError";
  }
};
var OAuthConnectionError = class extends OAuthError {
  constructor(message, options) {
    super(message, options);
    this.name = "OAuthConnectionError";
  }
};
var DeviceCodeTimeoutError = class extends OAuthError {
  constructor(message = "Device authorization timed out locally.") {
    super(message);
    this.name = "DeviceCodeTimeoutError";
  }
};
var RetryableRefreshError = class extends OAuthError {
  constructor(message) {
    super(message);
    this.name = "RetryableRefreshError";
  }
};

// vendor/kimi-oauth/utils.ts
function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// vendor/kimi-oauth/api-error.ts
var DIRECT_ERROR_KEYS = ["error_description", "message", "detail"];
var NESTED_ERROR_KEYS = ["message", "error_description", "detail", "code", "type"];
function extractApiErrorMessage(value) {
  if (Array.isArray(value)) {
    for (const item of value) {
      const message = extractApiErrorMessage(item);
      if (message !== void 0) return message;
    }
    return void 0;
  }
  if (!isRecord(value)) return void 0;
  for (const key of DIRECT_ERROR_KEYS) {
    const message = stringField(value, key);
    if (message !== void 0) return message;
  }
  const error = value["error"];
  const errorString = nonEmptyString(error);
  if (errorString !== void 0) return errorString;
  if (isRecord(error)) {
    for (const key of NESTED_ERROR_KEYS) {
      const message = stringField(error, key);
      if (message !== void 0) return message;
    }
  }
  const errors = value["errors"];
  if (Array.isArray(errors)) {
    for (const item of errors) {
      const message = extractApiErrorMessage(item);
      if (message !== void 0) return message;
    }
  }
  return void 0;
}
function stringField(record, key) {
  return nonEmptyString(record[key]);
}
function nonEmptyString(value) {
  if (typeof value !== "string") return void 0;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : void 0;
}

// vendor/kimi-oauth/oauth.ts
var RETRYABLE_STATUSES = /* @__PURE__ */ new Set([429, 500, 502, 503, 504]);
function pickErrorDetail(data) {
  return extractApiErrorMessage(data) ?? "unknown";
}
function tokenFromResponse(payload) {
  const accessToken = payload["access_token"];
  if (typeof accessToken !== "string" || accessToken.length === 0) {
    throw new OAuthError("OAuth response missing access_token");
  }
  const refreshToken = payload["refresh_token"];
  if (typeof refreshToken !== "string" || refreshToken.length === 0) {
    throw new OAuthError("OAuth response missing refresh_token");
  }
  const expiresInRaw = payload["expires_in"];
  const expiresIn = Number(expiresInRaw);
  if (!Number.isFinite(expiresIn) || expiresIn <= 0) {
    throw new OAuthError("OAuth response missing or invalid expires_in");
  }
  return {
    accessToken,
    refreshToken,
    expiresAt: Math.floor(Date.now() / 1e3) + expiresIn,
    scope: typeof payload["scope"] === "string" ? payload["scope"] : "",
    tokenType: typeof payload["token_type"] === "string" ? payload["token_type"] : "Bearer",
    expiresIn
  };
}
var DEFAULT_HTTP_TIMEOUT_MS = 3e4;
async function postForm(url, params, deviceHeaders, options) {
  const timeoutMs = options?.timeoutMs ?? DEFAULT_HTTP_TIMEOUT_MS;
  const body = new URLSearchParams(params).toString();
  const signals = [AbortSignal.timeout(timeoutMs)];
  if (options?.signal !== void 0) signals.push(options.signal);
  const signal = AbortSignal.any(signals);
  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: {
        ...deviceHeaders,
        "Content-Type": "application/x-www-form-urlencoded",
        Accept: "application/json"
      },
      body,
      signal
    });
  } catch (error) {
    throw new OAuthConnectionError(
      `OAuth request to ${url} failed: ${describeFetchFailure(error)}`,
      { cause: error }
    );
  }
  const status = response.status;
  let data = {};
  try {
    const parsed = await response.json();
    if (isRecord(parsed)) data = parsed;
  } catch {
  }
  return { status, data };
}
function describeFetchFailure(error) {
  if (!(error instanceof Error)) return String(error);
  const messages = /* @__PURE__ */ new Set();
  let current = error;
  while (current !== void 0) {
    messages.add(current.message);
    current = current.cause instanceof Error ? current.cause : void 0;
  }
  return [...messages].join(": ");
}
async function requestDeviceAuthorization(config, options) {
  const url = `${config.oauthHost.replace(/\/$/, "")}/api/oauth/device_authorization`;
  const { status, data } = await postForm(
    url,
    { client_id: config.clientId },
    options.deviceHeaders
  );
  if (status !== 200) {
    throw new OAuthError(
      `Device authorization failed (HTTP ${status}): ${pickErrorDetail(data)}`
    );
  }
  const userCode = data["user_code"];
  const deviceCode = data["device_code"];
  const verificationUriComplete = data["verification_uri_complete"];
  if (typeof userCode !== "string" || userCode.length === 0) {
    throw new OAuthError("Device authorization response missing user_code");
  }
  if (typeof deviceCode !== "string" || deviceCode.length === 0) {
    throw new OAuthError("Device authorization response missing device_code");
  }
  if (typeof verificationUriComplete !== "string" || verificationUriComplete.length === 0) {
    throw new OAuthError("Device authorization response missing verification_uri_complete");
  }
  return {
    userCode,
    deviceCode,
    verificationUri: typeof data["verification_uri"] === "string" ? data["verification_uri"] : "",
    verificationUriComplete,
    expiresIn: data["expires_in"] !== void 0 ? Number(data["expires_in"]) : null,
    interval: Number(data["interval"] ?? 5)
  };
}
async function pollDeviceToken(config, deviceCode, options) {
  const url = `${config.oauthHost.replace(/\/$/, "")}/api/oauth/token`;
  const { status, data } = await postForm(
    url,
    {
      client_id: config.clientId,
      device_code: deviceCode,
      grant_type: "urn:ietf:params:oauth:grant-type:device_code"
    },
    options.deviceHeaders
  );
  if (status === 200 && typeof data["access_token"] === "string") {
    return { kind: "success", token: tokenFromResponse(data) };
  }
  if (status >= 500) {
    throw new OAuthError(
      `Device token polling server error (HTTP ${status}): ${pickErrorDetail(data)}`
    );
  }
  const errorCode = typeof data["error"] === "string" ? data["error"] : "unknown_error";
  const detail = extractApiErrorMessage(data);
  const description = typeof data["error_description"] === "string" ? data["error_description"] : detail ?? "";
  switch (errorCode) {
    case "authorization_pending":
    case "slow_down":
      return { kind: "pending", errorCode, description };
    case "expired_token":
      return { kind: "expired" };
    case "access_denied":
      return { kind: "denied", description };
    default:
      throw new OAuthError(
        `Device token polling failed (HTTP ${status}): ${detail ?? `${errorCode} ${description}`}`
      );
  }
}
async function refreshAccessToken(config, refreshToken, options) {
  const maxRetries = options.maxRetries ?? 3;
  const backoff = options.backoffMs ?? ((attempt) => 2 ** attempt * 1e3);
  const sleep = options.sleep ?? ((ms) => new Promise((resolve2) => {
    setTimeout(resolve2, ms);
  }));
  const url = `${config.oauthHost.replace(/\/$/, "")}/api/oauth/token`;
  let lastError;
  for (let attempt = 0; attempt < maxRetries; attempt += 1) {
    let status;
    let data;
    try {
      ({ status, data } = await postForm(
        url,
        {
          client_id: config.clientId,
          grant_type: "refresh_token",
          refresh_token: refreshToken
        },
        options.deviceHeaders
      ));
    } catch (error) {
      lastError = error instanceof Error ? error : new OAuthError(String(error));
      if (attempt < maxRetries - 1) {
        await sleep(backoff(attempt));
        continue;
      }
      throw lastError instanceof Error ? lastError : new OAuthError(String(lastError));
    }
    if (status === 200 && typeof data["access_token"] === "string") {
      return tokenFromResponse(data);
    }
    const errorCode = typeof data["error"] === "string" ? data["error"] : "";
    const detail = extractApiErrorMessage(data);
    if (status === 401 || status === 403 || errorCode === "invalid_grant") {
      throw new OAuthUnauthorizedError(detail ?? "Token refresh unauthorized.");
    }
    const desc = detail ?? `Token refresh failed (HTTP ${status}).`;
    if (RETRYABLE_STATUSES.has(status)) {
      lastError = new RetryableRefreshError(desc);
      if (attempt < maxRetries - 1) {
        await sleep(backoff(attempt));
        continue;
      }
    } else {
      throw new OAuthError(desc);
    }
  }
  throw lastError ?? new OAuthError("Token refresh failed after retries.");
}

// vendor/kimi-oauth/token-state.ts
function classifyToken(token) {
  if (token === void 0) return { kind: "missing" };
  if (token.accessToken.length === 0) {
    return { kind: "revoked", scope: token.scope, tokenType: token.tokenType };
  }
  return { kind: "valid", token };
}
function revokedTombstone(prior) {
  return {
    accessToken: "",
    refreshToken: "",
    expiresAt: 0,
    scope: prior.scope,
    tokenType: prior.tokenType,
    expiresIn: 0
  };
}

// vendor/kimi-oauth/oauth-manager.ts
var MIN_REFRESH_THRESHOLD_SECONDS = 300;
var REFRESH_THRESHOLD_RATIO = 0.5;
var DEFAULT_DEVICE_CODE_TIMEOUT_MS = 15 * 60 * 1e3;
function defaultRefreshThreshold(expiresIn) {
  if (expiresIn > 0) {
    return Math.max(MIN_REFRESH_THRESHOLD_SECONDS, expiresIn * REFRESH_THRESHOLD_RATIO);
  }
  return MIN_REFRESH_THRESHOLD_SECONDS;
}
var defaultSleep = (ms) => new Promise((resolve2) => {
  setTimeout(resolve2, ms);
});
var OAuthManager = class {
  config;
  storage;
  refreshThresholdFn;
  deviceCodeTimeoutMs;
  now;
  sleep;
  refreshImpl;
  requestImpl;
  pollImpl;
  deviceHeaders;
  configDir;
  onRefresh;
  /**
   * In-flight refresh coalescer: one refresh per ensureFresh race.
   *
   * Tracks the `force` flag of the in-flight call so a later `force=true`
   * caller cannot piggyback a non-force result that may short-circuit on
   * a still-cached token. A non-force caller is happy with any settled
   * outcome and may piggyback either kind.
   */
  inFlightRefresh;
  constructor(options) {
    this.config = options.config;
    this.storage = options.storage;
    this.refreshThresholdFn = options.refreshThreshold ?? defaultRefreshThreshold;
    this.deviceCodeTimeoutMs = options.deviceCodeTimeoutMs ?? DEFAULT_DEVICE_CODE_TIMEOUT_MS;
    this.now = options.now ?? (() => Math.floor(Date.now() / 1e3));
    this.sleep = options.sleep ?? defaultSleep;
    this.deviceHeaders = options.deviceHeaders;
    this.onRefresh = options.onRefresh;
    this.refreshImpl = options.refreshTokenImpl ?? ((config, refreshToken, refreshOptions) => refreshAccessToken(config, refreshToken, {
      ...refreshOptions,
      deviceHeaders: this.resolveDeviceHeaders()
    }));
    this.requestImpl = options.requestDeviceImpl ?? ((config) => requestDeviceAuthorization(config, {
      deviceHeaders: this.resolveDeviceHeaders()
    }));
    this.pollImpl = options.pollDeviceImpl ?? ((config, deviceCode) => pollDeviceToken(config, deviceCode, {
      deviceHeaders: this.resolveDeviceHeaders()
    }));
    const envConfigDir = process.env["NODE_ENV"] === "test" ? process.env["KIMI_CODE_HOME"] : void 0;
    this.configDir = options.configDir ?? envConfigDir;
  }
  resolveDeviceHeaders() {
    return this.deviceHeaders?.();
  }
  async loadState() {
    return classifyToken(await this.storage.load(this.config.name));
  }
  notifyRefresh(outcome) {
    if (this.onRefresh === void 0) return;
    try {
      this.onRefresh(outcome);
    } catch {
    }
  }
  /**
   * Resolve the sentinel target file `proper-lockfile` locks against.
   * `proper-lockfile.lock(target)` creates `${target}.lock` as the
   * actual lock directory, so the real lockfile on disk ends up at
   * `{configDir}/oauth/{providerName}.lock`. Returns `undefined` when
   * locking is opted out (no configDir, Windows, env kill switch).
   */
  resolveLockTarget() {
    if (process.platform === "win32") return void 0;
    if (process.env["KIMI_DISABLE_OAUTH_LOCK"] === "1") return void 0;
    if (this.configDir === void 0) return void 0;
    return `${this.configDir}/oauth/${this.config.name}`;
  }
  /**
   * Acquire the cross-process lock around the refresh critical section.
   * Returns a `release` closure; when locking is disabled returns a no-op.
   * If locking is configured but cannot be acquired, fail closed rather than
   * refreshing with no lock and racing refresh_token rotation.
   */
  async acquireRefreshLock() {
    const target = this.resolveLockTarget();
    if (target === void 0) return async () => {
    };
    try {
      await mkdir(dirname(target), { recursive: true });
      await writeFile(target, "", { flag: "a" });
    } catch (error) {
      throw new OAuthError(
        `Unable to prepare OAuth refresh lock for "${this.config.name}": ${error instanceof Error ? error.message : String(error)}`
      );
    }
    try {
      const release2 = await import_proper_lockfile.default.lock(target, {
        retries: { retries: 120, factor: 1, minTimeout: 500, maxTimeout: 1e3 },
        stale: 5e3,
        realpath: false
      });
      return async () => {
        try {
          await release2();
        } catch {
        }
      };
    } catch (error) {
      throw new OAuthError(
        `Unable to acquire OAuth refresh lock for "${this.config.name}": ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }
  async hasToken() {
    return (await this.loadState()).kind === "valid";
  }
  async getCachedAccessToken() {
    const state = await this.loadState();
    return state.kind === "valid" ? state.token.accessToken : void 0;
  }
  async logout() {
    await this.storage.remove(this.config.name);
  }
  /**
   * Return a valid access_token, refreshing if within the dynamic threshold.
   * Throws if no token is persisted (caller should invoke `/login`).
   */
  async ensureFresh(options = {}) {
    const force = options.force === true;
    const current = this.inFlightRefresh;
    if (current !== void 0) {
      if (!force || current.force) {
        return current.promise;
      }
      return current.promise.catch(() => void 0).then(() => this.ensureFresh(options));
    }
    const promise = this.doEnsureFresh(force).finally(() => {
      if (this.inFlightRefresh?.promise === promise) {
        this.inFlightRefresh = void 0;
      }
    });
    this.inFlightRefresh = { promise, force };
    return promise;
  }
  async doEnsureFresh(force) {
    const initial = await this.loadState();
    switch (initial.kind) {
      case "missing":
        throw new OAuthUnauthorizedError(
          `No token for "${this.config.name}". Run /login to authenticate.`
        );
      case "revoked":
        throw new OAuthUnauthorizedError(
          `Stored token for "${this.config.name}" was rejected; re-login required.`
        );
      case "valid":
        break;
    }
    const token = initial.token;
    const needRefresh = this.shouldRefreshToken(token, force);
    if (!needRefresh) {
      return token.accessToken;
    }
    const release2 = await this.acquireRefreshLock();
    try {
      const afterLock = await this.loadState();
      let activeToken;
      switch (afterLock.kind) {
        case "revoked":
          throw new OAuthUnauthorizedError(
            `Stored token for "${this.config.name}" was rejected; re-login required.`
          );
        case "missing":
          activeToken = token;
          break;
        case "valid": {
          const after = afterLock.token;
          if (!this.shouldRefreshToken(after, force)) {
            return after.accessToken;
          }
          if (force) {
            const changedWhileWaiting = after.refreshToken !== token.refreshToken || after.accessToken !== token.accessToken || after.expiresAt !== token.expiresAt || after.expiresIn !== token.expiresIn;
            if (changedWhileWaiting) {
              return after.accessToken;
            }
          }
          activeToken = after;
          break;
        }
      }
      if (activeToken.refreshToken.length === 0) {
        throw new OAuthUnauthorizedError(
          `Token for "${this.config.name}" has no refresh_token; re-login required.`
        );
      }
      try {
        const refreshed = await this.refreshImpl(this.config, activeToken.refreshToken);
        await this.storage.save(this.config.name, refreshed);
        this.notifyRefresh({ success: true });
        return refreshed.accessToken;
      } catch (error) {
        if (error instanceof OAuthUnauthorizedError) {
          await this.sleep(100);
          const recovery = await this.loadState();
          if (recovery.kind === "valid" && recovery.token.refreshToken !== activeToken.refreshToken) {
            this.notifyRefresh({ success: true });
            return recovery.token.accessToken;
          }
          await this.storage.save(this.config.name, revokedTombstone(activeToken));
          this.notifyRefresh({ success: false, reason: "unauthorized" });
        } else {
          this.notifyRefresh({ success: false, reason: "network_or_other" });
        }
        throw error;
      }
    } finally {
      await release2();
    }
  }
  /**
   * Drive the device code flow end-to-end. `onDeviceCode` is called once
   * the user code is available so the caller can display it.
   *
   * Local 15-min wall-clock budget guards against forever-pending flows.
   */
  async login(options = {}) {
    const startedAt = this.now();
    const deadlineAt = startedAt + Math.ceil(this.deviceCodeTimeoutMs / 1e3);
    while (true) {
      const auth = await this.requestImpl(this.config);
      await options.onDeviceCode?.(auth);
      let currentInterval = Math.max(auth.interval, 1);
      let deviceExpired = false;
      while (true) {
        this.throwIfAborted(options.signal);
        if (this.now() >= deadlineAt) {
          throw new DeviceCodeTimeoutError(
            `Device authorization timed out after ${Math.ceil(this.deviceCodeTimeoutMs / 1e3)}s`
          );
        }
        const result = await this.pollImpl(this.config, auth.deviceCode);
        if (result.kind === "success") {
          await this.storage.save(this.config.name, result.token);
          return result.token;
        }
        if (result.kind === "denied") {
          throw new OAuthAccessDeniedError(
            `Authorization denied${result.description ? `: ${result.description}` : ""}`
          );
        }
        if (result.kind === "expired") {
          deviceExpired = true;
          break;
        }
        if (result.errorCode === "slow_down") {
          currentInterval += 5;
        }
        await this.sleep(currentInterval * 1e3);
      }
      if (!deviceExpired) break;
      if (this.now() >= deadlineAt) {
        throw new DeviceCodeTimeoutError("Device authorization timed out");
      }
    }
    throw new OAuthError("Device flow ended unexpectedly");
  }
  shouldRefreshToken(token, force) {
    if (force) return true;
    if (token.expiresAt === 0) return false;
    const remaining = token.expiresAt - this.now();
    return remaining < this.refreshThresholdFn(token.expiresIn);
  }
  throwIfAborted(signal) {
    if (signal?.aborted === true) {
      throw new OAuthError("Login aborted by caller");
    }
  }
};

// vendor/kimi-oauth/storage.ts
import { randomBytes } from "node:crypto";
import {
  chmodSync,
  closeSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readdirSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeSync
} from "node:fs";
import { basename, join } from "node:path";

// vendor/kimi-oauth/types.ts
function tokenToWire(token) {
  return {
    access_token: token.accessToken,
    refresh_token: token.refreshToken,
    expires_at: token.expiresAt,
    scope: token.scope,
    token_type: token.tokenType,
    expires_in: token.expiresIn
  };
}
function tokenFromWire(wire) {
  return {
    accessToken: wire.access_token ?? "",
    refreshToken: wire.refresh_token ?? "",
    expiresAt: typeof wire.expires_at === "number" ? wire.expires_at : 0,
    scope: wire.scope ?? "",
    tokenType: wire.token_type ?? "",
    expiresIn: typeof wire.expires_in === "number" ? wire.expires_in : 0
  };
}

// vendor/kimi-oauth/storage.ts
var FileTokenStorage = class {
  dir;
  constructor(dir) {
    this.dir = dir;
  }
  ensureDir() {
    mkdirSync(this.dir, { recursive: true, mode: 448 });
    try {
      chmodSync(this.dir, 448);
    } catch {
    }
  }
  pathFor(name) {
    const safe = basename(name);
    if (safe.length === 0 || safe !== name || safe.startsWith(".")) {
      throw new Error(`Invalid token name: "${name}"`);
    }
    return join(this.dir, `${safe}.json`);
  }
  async load(name) {
    const file = this.pathFor(name);
    let raw;
    try {
      raw = readFileSync(file, "utf-8");
    } catch {
      return void 0;
    }
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return void 0;
    }
    if (!isRecord(parsed)) return void 0;
    return tokenFromWire(parsed);
  }
  async save(name, token) {
    this.ensureDir();
    const target = this.pathFor(name);
    const tmp = `${target}.tmp.${process.pid}.${randomBytes(4).toString("hex")}`;
    const data = Buffer.from(`${JSON.stringify(tokenToWire(token), null, 2)}
`, "utf-8");
    const fd = openSync(tmp, "w", 384);
    try {
      let written = 0;
      while (written < data.length) {
        written += writeSync(fd, data, written, data.length - written);
      }
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
    try {
      chmodSync(tmp, 384);
      renameSync(tmp, target);
    } catch (error) {
      try {
        unlinkSync(tmp);
      } catch {
      }
      throw error;
    }
  }
  async remove(name) {
    try {
      unlinkSync(this.pathFor(name));
    } catch (error) {
      if (error.code !== "ENOENT") {
        throw error;
      }
    }
  }
  async list() {
    let entries;
    try {
      entries = readdirSync(this.dir);
    } catch {
      return [];
    }
    return entries.filter((e) => e.endsWith(".json")).map((e) => e.slice(0, -".json".length));
  }
};

// vendor/kimi-oauth/constants.ts
var DEFAULT_KIMI_CODE_OAUTH_HOST = "https://auth.kimi.com";
function envOverride(key) {
  const proc = globalThis.process;
  return proc?.env?.[key];
}
var KIMI_CODE_FLOW_CONFIG = {
  name: "kimi-code",
  oauthHost: envOverride("KIMI_CODE_OAUTH_HOST") ?? envOverride("KIMI_OAUTH_HOST") ?? DEFAULT_KIMI_CODE_OAUTH_HOST,
  clientId: "17e5f671-d194-4dfb-9706-5516cb48c098"
};

// vendor/kimi-oauth/identity.ts
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync as mkdirSync2, readFileSync as readFileSync2, writeFileSync } from "node:fs";
import { arch, hostname, release, type } from "node:os";
import { join as join2 } from "node:path";
function readKimiDeviceId(homeDir) {
  const deviceIdPath = join2(homeDir, "device_id");
  if (!existsSync(deviceIdPath)) return null;
  try {
    const text = readFileSync2(deviceIdPath, "utf-8").trim();
    return text.length > 0 ? text : null;
  } catch {
    return null;
  }
}
function createKimiDeviceId(homeDir, options = {}) {
  const existing = readKimiDeviceId(homeDir);
  if (existing !== null) return existing;
  const id = randomUUID();
  try {
    mkdirSync2(homeDir, { recursive: true, mode: 448 });
    writeFileSync(join2(homeDir, "device_id"), id, { encoding: "utf-8", mode: 384 });
  } catch {
  }
  if (options.onFirstLaunch !== void 0) {
    try {
      options.onFirstLaunch(id);
    } catch {
    }
  }
  return id;
}
function createKimiDeviceHeaders(options) {
  return {
    "X-Msh-Platform": requiredAsciiHeader(options.platform, "Kimi identity platform"),
    "X-Msh-Version": requiredAsciiHeader(options.version, "Kimi identity version"),
    "X-Msh-Device-Name": asciiHeader(hostname()),
    "X-Msh-Device-Model": asciiHeader(deviceModel()),
    "X-Msh-Os-Version": asciiHeader(release()),
    "X-Msh-Device-Id": createKimiDeviceId(options.homeDir)
  };
}
function createKimiUserAgent(options) {
  const product = requiredAsciiHeader(options.productName, "Kimi identity product");
  const version = requiredAsciiHeader(options.version, "Kimi identity version");
  const suffix = options.userAgentSuffix === void 0 ? void 0 : asciiHeader(options.userAgentSuffix, "");
  return suffix === void 0 || suffix.length === 0 ? `${product}/${version}` : `${product}/${version} (${suffix})`;
}
function createKimiDefaultHeaders(options) {
  return {
    "User-Agent": createKimiUserAgent(options),
    ...createKimiDeviceHeaders({
      homeDir: options.homeDir,
      version: options.version,
      platform: options.platform
    })
  };
}
function deviceModel() {
  const os = type();
  const version = release();
  const osArch = arch();
  if (os === "Darwin") return `macOS ${macOsProductVersion() ?? version} ${osArch}`;
  if (os === "Windows_NT") return `Windows ${version} ${osArch}`;
  return `${os} ${version} ${osArch}`.trim();
}
var MACOS_SYSTEM_VERSION_PLIST = "/System/Library/CoreServices/SystemVersion.plist";
function macOsProductVersion() {
  try {
    const plist = readFileSync2(MACOS_SYSTEM_VERSION_PLIST, "utf-8");
    const version = /<key>ProductVersion<\/key>\s*<string>([^<]*)<\/string>/.exec(plist)?.[1]?.trim();
    return version !== void 0 && version.length > 0 ? version : void 0;
  } catch {
    return void 0;
  }
}
function asciiHeader(value, fallback = "unknown") {
  const cleaned = value.replaceAll(/[^\u0020-\u007E]/g, "").trim();
  return cleaned.length > 0 ? cleaned : fallback;
}
function requiredAsciiHeader(value, fieldName) {
  const cleaned = asciiHeader(value, "");
  if (cleaned.length === 0) {
    throw new Error(`${fieldName} must be a non-empty ASCII string.`);
  }
  return cleaned;
}

// bridge/auth.ts
async function main() {
  let input = "";
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > 65536) throw new Error("Input too large");
  }
  const request = JSON.parse(input);
  const home = resolve(request.home);
  const headers = createKimiDefaultHeaders({
    homeDir: home,
    productName: "kimi-codex-memory",
    version: request.version,
    platform: "kimi_code_cli",
    userAgentSuffix: "Kimi Code memory plugin"
  });
  if (request.operation === "headers") {
    process.stdout.write(JSON.stringify({ headers }));
    return;
  }
  const key = request.key;
  const name = key === "oauth/kimi-code" || key === "kimi-code" ? "kimi-code" : key.startsWith("oauth/") ? key.slice(6) : key;
  if (!/^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,199}$/.test(name)) throw new Error("Invalid token key");
  const host = new URL(request.oauth_host || KIMI_CODE_FLOW_CONFIG.oauthHost);
  if (host.username || host.password || host.search || host.hash || host.protocol !== "https:" && !["127.0.0.1", "[::1]", "localhost"].includes(host.hostname)) {
    throw new Error("Unsafe OAuth endpoint");
  }
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (url, init) => originalFetch(url, { ...init, redirect: "error" });
  const manager = new OAuthManager({
    config: { ...KIMI_CODE_FLOW_CONFIG, name, oauthHost: host.href.endsWith("/") ? host.href.slice(0, -1) : host.href },
    storage: new FileTokenStorage(join3(home, "credentials")),
    configDir: home,
    deviceHeaders: () => headers
  });
  const access_token = await manager.ensureFresh({ force: request.force === true });
  process.stdout.write(JSON.stringify({ access_token, headers }));
}
main().catch(() => {
  process.stdout.write(JSON.stringify({ error: "Kimi authentication unavailable" }));
  process.exitCode = 1;
});
