CouchPotato
=====

[![Join the chat at https://gitter.im/CouchPotato/CouchPotatoServer](https://badges.gitter.im/Join%20Chat.svg)](https://gitter.im/CouchPotato/CouchPotatoServer?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge)
[![CI](https://github.com/bassings/CouchPotatoServer/actions/workflows/ci.yml/badge.svg)](https://github.com/bassings/CouchPotatoServer/actions/workflows/ci.yml)
[![Docker](https://github.com/bassings/CouchPotatoServer/actions/workflows/docker.yml/badge.svg)](https://github.com/bassings/CouchPotatoServer/actions/workflows/docker.yml)
[![Coverage Status](https://coveralls.io/repos/bassings/CouchPotatoServer/badge.svg?branch=master&service=github)](https://coveralls.io/github/bassings/CouchPotatoServer?branch=master)

CouchPotato (CP) is an automatic NZB and torrent downloader. You can keep a "movies I want"-list and it will search for NZBs/torrents of these movies every X hours.
Once a movie is found, it will send it to SABnzbd or download the torrent to a specified directory.

## 🐍 Python 3 Migration Complete!

**This fork has been successfully migrated to Python 3.13** and is fully operational. The migration includes:

- ✅ **Full Python 3.8+ compatibility** (tested on Python 3.13)
- ✅ **All core functionality preserved** 
- ✅ **Web interface fully operational**
- ✅ **Database migration handled automatically**
- ✅ **Comprehensive test suite for compatibility**

## Requirements

- **Python 3.8 or higher** (recommended: Python 3.10+)
- Git (for updates from source)
- Optional: LXML for better/faster website scraping

## Running from Source

CouchPotatoServer can be run from source. This will use *git* as updater, so make sure that is installed.

Windows:

* Install [Python 3.8+](https://www.python.org/downloads/) (recommended: latest stable version)
* Then install [PyWin32](https://pypi.org/project/pywin32/) with `pip install pywin32` and [GIT](http://git-scm.com/)
* Open up `Git Bash` (or CMD) and go to the folder you want to install CP. Something like Program Files.
* Run `git clone https://github.com/bassings/CouchPotatoServer.git`.
* You can now start CP via `python CouchPotatoServer\CouchPotato.py` to start
* Your browser should open up, but if it doesn't go to `http://localhost:5050/`

OS X:

* Install [Python 3.8+](https://www.python.org/downloads/) (macOS 10.15+ recommended)
* Install [GIT](http://git-scm.com/)
* Install [LXML](http://lxml.de/installation.html) with `pip install lxml` for better/faster website scraping 
* Open up `Terminal`
* Go to your App folder `cd /Applications`
* Run `git clone https://github.com/bassings/CouchPotatoServer.git`
* Then do `python3 CouchPotatoServer/CouchPotato.py`
* Your browser should open up, but if it doesn't go to `http://localhost:5050/`

Linux:

* (Ubuntu / Debian) Install Python 3.8+ and GIT: `apt-get install python3 python3-pip git`
* (Fedora / CentOS) Install Python 3.8+ and GIT: `dnf install python3 python3-pip git`
* Install [LXML](http://lxml.de/installation.html) with `pip3 install lxml` for better/faster website scraping 
* 'cd' to the folder of your choosing.
* Install [PyOpenSSL](https://pypi.python.org/pypi/pyOpenSSL) with `pip3 install --upgrade pyopenssl`
* Run `git clone https://github.com/bassings/CouchPotatoServer.git`
* Then do `python3 CouchPotatoServer/CouchPotato.py` to start
* (Ubuntu / Debian with upstart) To run on boot copy the init script `sudo cp CouchPotatoServer/init/ubuntu /etc/init.d/couchpotato`
* (Ubuntu / Debian with upstart) Copy the default paths file `sudo cp CouchPotatoServer/init/ubuntu.default /etc/default/couchpotato`
* (Ubuntu / Debian with upstart) Change the paths inside the default file `sudo nano /etc/default/couchpotato`
* (Ubuntu / Debian with upstart) Make it executable `sudo chmod +x /etc/init.d/couchpotato`
* (Ubuntu / Debian with upstart) Add it to defaults `sudo update-rc.d couchpotato defaults`
* (Linux with systemd) To run on boot copy the systemd config `sudo cp CouchPotatoServer/init/couchpotato.service /etc/systemd/system/couchpotato.service`
* (Linux with systemd) Update the systemd config file with your user and path to CouchPotato.py (ensure it uses `python3`)
* (Linux with systemd) Enable it at boot with `sudo systemctl enable couchpotato`
* Open your browser and go to `http://localhost:5050/`

Docker:
* You can use [linuxserver.io](https://github.com/linuxserver/docker-couchpotato) or build your own container based on Python 3.8+. For more info about Docker check out the [official website](https://www.docker.com).

FreeBSD:

* Become root with `su`
* Update your repo catalog `pkg update`
* Install required tools `pkg install python3 py39-sqlite3 git-lite`
* For default install location and running as root `cd /usr/local`
* If running as root, create python3 symlink `ln -s /usr/local/bin/python3 /usr/bin/python3`
* Run `git clone https://github.com/bassings/CouchPotatoServer.git`
* Copy the startup script `cp CouchPotatoServer/init/freebsd /usr/local/etc/rc.d/couchpotato`
* Edit the startup script to use `python3` instead of `python`
* Make startup script executable `chmod 555 /usr/local/etc/rc.d/couchpotato`
* Add startup to boot `echo 'couchpotato_enable="YES"' >> /etc/rc.conf`
* Read the options at the top of `more /usr/local/etc/rc.d/couchpotato`
* If not default install, specify options with startup flags in `ee /etc/rc.conf`
* Finally, `service couchpotato start`
* Open your browser and go to: `http://server:5050/`

## Migration from Python 2

If you're migrating from a Python 2 installation:

1. **Backup your data**: Copy your existing `data/` directory
2. **Install Python 3.8+**: Follow the installation instructions above
3. **Clone this repository**: `git clone https://github.com/bassings/CouchPotatoServer.git`
4. **Copy your data**: Move your backed up `data/` directory to the new installation
5. **Start with Python 3**: Run `python3 CouchPotato.py`

The application will automatically handle any necessary database migrations.

## Development

Be sure you're running the latest version of **Python 3.8 or higher** (Python 3.10+ recommended).

If you're going to add styling or doing some javascript work you'll need a few tools that build and compress scss -> css and combine the javascript files. [Node/NPM](https://nodejs.org/), [Grunt](http://gruntjs.com/installing-grunt), [Compass](http://compass-style.org/install/)

After you've got these tools you can install the packages using `npm install`. Once this process has finished you can start CP using the command `grunt`. This will start all the needed tools and watches any files for changes.
You can now change css and javascript and it wil reload the page when needed.

By default it will combine files used in the core folder. If you're adding a new .scss or .js file, you might need to add it and then restart the grunt process for it to combine it properly.

Don't forget to enable development inside the CP settings. This disables some functions and also makes sure javascript errors are pushed to console instead of the log.

## Testing

This fork includes comprehensive Python 3 compatibility tests:

```bash
# Run compatibility tests
python3 test_python3_compatibility.py

# Run integration tests  
python3 test_couchpotato_integration.py
```

## Contributing

We welcome contributions! This fork focuses on:

- Python 3 compatibility and improvements
- Bug fixes and stability improvements  
- Security updates
- Performance optimizations

Please ensure any contributions maintain Python 3.8+ compatibility.

## Python 3 Migration Notes

This fork has been extensively tested and includes fixes for:

- Dictionary iteration compatibility (`iterkeys()` → `keys()`)
- String/bytes encoding issues
- Function introspection updates
- Import compatibility (Tornado, etc.)
- Database migration handling
- Hash function encoding requirements

All core functionality has been preserved and thoroughly tested.
