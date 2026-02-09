#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2011-2013 Codernity (http://codernity.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


__version__ = '0.5.0'
__license__ = "Apache 2.0"

# Ensure CodernityDB directory is on sys.path for bare imports (rr_cache, etc.)
import os, sys
_cdb_dir = os.path.dirname(os.path.abspath(__file__))
if _cdb_dir not in sys.path:
    sys.path.insert(0, _cdb_dir)
