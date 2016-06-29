#!/bin/env python

# Copyright (c) 2002-2016, California Institute of Technology.
# All rights reserved.  Based on Government Sponsored Research under contracts NAS7-1407 and/or NAS7-03001.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#   1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
#   2. Redistributions in binary form must reproduce the above copyright notice,
#      this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
#   3. Neither the name of the California Institute of Technology (Caltech), its operating division the Jet Propulsion Laboratory (JPL),
#      the National Aeronautics and Space Administration (NASA), nor the names of its contributors may be used to
#      endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE CALIFORNIA INSTITUTE OF TECHNOLOGY BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
# EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
# http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#
# Pipeline for converting vector-based datasets into standardized vector tiles, rasterized tiles, and GeoJSON.
#
# Example:
#
#  vectorgen.py 
#   -c vectorgen_configuration_file.xml 
#   -s http://localhost:8100/sigevent/events/create

from optparse import OptionParser
from oe_utils import *
import glob
import logging
import os
import sys
import time
import xml.dom.minidom
import string
import shutil
try:
    from osgeo import ogr, osr, gdal
except:
    sys.exit('ERROR: cannot find GDAL/OGR modules')

versionNumber = '1.0.0'
basename = None

def shp2geojson(in_filename, out_filename, sigevent_url):
    """
    Converts Esri Shapefile into GeoJSON.
    Arguments:
        in_filename -- the input Shapefile
        out_filename -- the output GeoJSON file
        sigevent_url -- the URL for SigEvent
    """
    ogr2ogr_command_list = ['ogr2ogr', '-f', 'GeoJSON', out_filename, in_filename]
    run_command(ogr2ogr_command_list, sigevent_url)

if __name__ == '__main__':
    
    # Declare counter for errors
    errors = 0
    
    # Define command line options and args.
    parser = OptionParser(version = versionNumber)
    parser.add_option('-c', '--configuration_filename',
                      action='store', type='string', dest='configuration_filename',
                      default='./vectorgen_configuration_file.xml',
                      help='Full path of configuration filename.  Default:  ./vectorgen_configuration_file.xml')
    parser.add_option("-d", "--data_only", action="store_true", dest="data_only", 
                      default=False, help="Only output the MRF data, index, and header files")
    parser.add_option('-s', '--sigevent_url',
                      action='store', type='string', dest='sigevent_url',
                      default=
                      'http://localhost:8100/sigevent/events/create',
                      help='Default:  http://localhost:8100/sigevent/events/create')
    
    # Read command line args.
    (options, args) = parser.parse_args()
    # Configuration filename.
    configuration_filename=options.configuration_filename
    # Sigevent URL.
    sigevent_url=options.sigevent_url
    # Data only.
    data_only = options.data_only
    
    # Get current time, which is written to a file as the previous cycle time.  
    # Time format is "yyyymmdd.hhmmss".  Do this first to avoid any gap where tiles 
    # may get passed over because they were created while this script is running.
    current_cycle_time=time.strftime('%Y%m%d.%H%M%S', time.localtime())
    
    # Read XML configuration file.
    try:
        # Open file.
        config_file=open(configuration_filename, 'r')
    except IOError:
        mssg=str().join(['Cannot read configuration file:  ', configuration_filename])
        log_sig_exit('ERROR', mssg, sigevent_url)
    else:
        # Get dom from XML file.
        dom=xml.dom.minidom.parse(config_file)
        # Parameter name.
        parameter_name = get_dom_tag_value(dom, 'parameter_name')
        date_of_data = get_dom_tag_value(dom, 'date_of_data')
    
        # Define output basename
        basename=str().join([parameter_name, '_', date_of_data, '___', 'vectorgen_', current_cycle_time])    
        
        # for sub-daily imagery
        try: 
            time_of_data = get_dom_tag_value(dom, 'time_of_data')
        except:
            time_of_data = ''
        # Directories.
        try:
            input_dir = get_dom_tag_value(dom, 'input_dir')
        except: 
            input_dir = None
        output_dir = get_dom_tag_value(dom, 'output_dir')
        try:
            working_dir = get_dom_tag_value(dom, 'working_dir')
            working_dir = add_trailing_slash(check_abs_path(working_dir))
        except: # use /tmp/ as default
            working_dir ='/tmp/'
        try:
            logfile_dir = get_dom_tag_value(dom, 'logfile_dir')
        except: #use working_dir if not specified
            logfile_dir = working_dir
        try:
            output_name=get_dom_tag_value(dom, 'output_name')
        except:
            # default to GIBS naming convention
            output_name='{$parameter_name}%Y%j_.json'
        output_format = string.lower(get_dom_tag_value(dom, 'output_format'))
        try:
            outsize = get_dom_tag_value(dom, 'outsize')
            target_x, target_y = outsize.split(' ')
        except:
            outsize = ''
            try:
                target_x = get_dom_tag_value(dom, 'target_x')
            except:
                target_x = '' # if no target_x then use rasterXSize and rasterYSize from VRT file
            try:
                target_y = get_dom_tag_value(dom, 'target_y')
            except:
                target_y = ''
        # EPSG code projection.
        try:
            target_epsg = 'EPSG:' + str(get_dom_tag_value(dom, 'target_epsg'))
        except:
            target_epsg = 'EPSG:4326' # default to geographic
        try:
            source_epsg = 'EPSG:' + str(get_dom_tag_value(dom, 'source_epsg'))
        except:
            source_epsg = 'EPSG:4326' # default to geographic
        # Target extents.
        try:
            extents = get_dom_tag_value(dom, 'extents')
        except:
            extents = '-180,-90,180,90' # default to geographic
        xmin, ymin, xmax, ymax = extents.split(',')
        try:
            target_extents = get_dom_tag_value(dom, 'target_extents')
        except:
            if target_epsg == 'EPSG:3857':
                target_extents = '-20037508.34,-20037508.34,20037508.34,20037508.34'
            else:
                target_extents = extents # default to extents
        target_xmin, target_ymin, target_xmax, target_ymax = target_extents.split(',')
        # Input files.
        try:
            input_files = get_input_files(dom)
            if input_files == '':
                raise ValueError('No input files provided')
        except:
            if input_dir == None:
                log_sig_exit('ERROR', "<input_files> or <input_dir> is required", sigevent_url)
            else:
                input_files = ''

        # Close file.
        config_file.close()
    
    # Make certain each directory exists and has a trailing slash.
    if input_dir != None:
        input_dir = add_trailing_slash(check_abs_path(input_dir))
    output_dir = add_trailing_slash(check_abs_path(output_dir))
    logfile_dir = add_trailing_slash(check_abs_path(logfile_dir))
    
    # Save script_dir
    script_dir = add_trailing_slash(os.path.dirname(os.path.abspath(__file__)))
    
    # Verify logfile_dir first so that the log can be started.
    verify_directory_path_exists(logfile_dir, 'logfile_dir', sigevent_url)
    # Initialize log file.
    log_filename=str().join([logfile_dir, basename, '.log'])
    logging.basicConfig(filename=log_filename, level=logging.INFO)
    
    # Verify remaining directory paths.
    if input_dir != None:
        verify_directory_path_exists(input_dir, 'input_dir', sigevent_url)
    verify_directory_path_exists(output_dir, 'output_dir', sigevent_url)
    verify_directory_path_exists(working_dir, 'working_dir', sigevent_url)
    
    # Log all of the configuration information.
    log_info_mssg_with_timestamp(str().join(['config XML file:                ', configuration_filename]))                                      
    # Copy configuration file to working_dir (if it's not already there) so that the output can be recreated if needed.
    if os.path.dirname(configuration_filename) != os.path.dirname(working_dir):
        config_preexisting=glob.glob(configuration_filename)
        if len(config_preexisting) > 0:
            at_dest_filename=str().join([working_dir, configuration_filename])
            at_dest_preexisting=glob.glob(at_dest_filename)
            if len(at_dest_preexisting) > 0:
                remove_file(at_dest_filename)
            shutil.copy(configuration_filename, working_dir+"/"+basename+".configuration_file.xml")
            log_info_mssg(str().join([
                              'config XML file copied to       ', working_dir]))
    log_info_mssg(str().join(['config parameter_name:          ', parameter_name]))
    log_info_mssg(str().join(['config date_of_data:            ', date_of_data]))
    log_info_mssg(str().join(['config time_of_data:            ', time_of_data]))
    if input_files != '':
        log_info_mssg(str().join(['config input_files:             ', input_files]))
    if input_dir != None:
        log_info_mssg(str().join(['config input_dir:               ', input_dir]))
    log_info_mssg(str().join(['config output_dir:              ', output_dir]))
    log_info_mssg(str().join(['config working_dir:             ', working_dir]))
    log_info_mssg(str().join(['config logfile_dir:             ', logfile_dir]))
    log_info_mssg(str().join(['config output_name:             ', output_name]))
    log_info_mssg(str().join(['config output_format:           ', output_format]))
    log_info_mssg(str().join(['config outsize:                 ', outsize]))
    log_info_mssg(str().join(['config target_x:                ', target_x]))
    log_info_mssg(str().join(['config target_y:                ', target_y]))
    log_info_mssg(str().join(['config target_epsg:             ', target_epsg]))
    log_info_mssg(str().join(['config source_epsg:             ', source_epsg]))
    log_info_mssg(str().join(['config extents:                 ', extents]))
    log_info_mssg(str().join(['config target_extents:          ', target_extents]))
    log_info_mssg(str().join(['vectorgen current_cycle_time:   ', current_cycle_time]))
    log_info_mssg(str().join(['vectorgen basename:             ', basename]))
    
    # Verify that date is 8 characters.
    if len(date_of_data) != 8:
        mssg='Format for <date_of_data> (in vectorgen XML config file) is:  yyyymmdd'
        log_sig_exit('ERROR', mssg, sigevent_url)
        
    if time_of_data != '' and len(time_of_data) != 6:
        mssg='Format for <time_of_data> (in vectorgen XML config file) is:  HHMMSS'
        log_sig_exit('ERROR', mssg, sigevent_url)
    
    # Change directory to working_dir.
    os.chdir(working_dir)
    
    # Get list of all tile filenames.
    alltiles = []
    if input_files != '':
        input_files = input_files.strip()
        alltiles = input_files.split(',')
    if input_dir != None:
        if output_format == 'geojson' or output_format == 'json':
            alltiles = alltiles + glob.glob(str().join([input_dir, '*json']))
        else:
            alltiles = alltiles + glob.glob(str().join([input_dir, '*']))
    
    striptiles = []
    for tile in alltiles:
        striptiles.append(tile.strip())
    alltiles = striptiles
    
    if len(time_of_data) == 6:
        mrf_date = datetime.datetime.strptime(str(date_of_data)+str(time_of_data),"%Y%m%d%H%M%S")
    else: 
        mrf_date = datetime.datetime.strptime(date_of_data,"%Y%m%d")
    out_filename = output_name.replace('{$parameter_name}', parameter_name)
    time_params = []
    for i, char in enumerate(out_filename):
        if char == '%':
            time_params.append(char+out_filename[i+1])
    for time_param in time_params:
        out_filename = out_filename.replace(time_param,datetime.datetime.strftime(mrf_date,time_param))
    
    out_basename = output_dir + basename
    out_filename = output_dir + out_filename
            
    if len(alltiles) > 0 and output_format == "geojson":
        out_basename = out_basename + ".json"
        shp2geojson(alltiles[0], out_basename, sigevent_url)
        log_info_mssg(str().join(['Moving ', out_basename, ' to ', out_filename]))
        shutil.move(out_basename, out_filename)
    else:
        log_sig_exit('ERROR', "No valid input files found", sigevent_url)
    
    # Send to log.
    mssg=str().join(['Output created:  ', out_filename])
    try:
        log_info_mssg(mssg)
        sigevent('INFO', mssg, sigevent_url)
    except urllib2.URLError:
        None
    sys.exit(errors)