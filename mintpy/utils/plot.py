############################################################
# Program is part of MintPy                                #
# Copyright(c) 2018-2019, Zhang Yunjun                     #
# Author:  Zhang Yunjun, 2018                              #
############################################################
# Recommend import:
#     from mintpy.utils import plot as pp


import os
import glob
import argparse
import warnings
import datetime
import h5py
import numpy as np

import matplotlib as mpl
from matplotlib import (dates as mdates,
                        lines as mlines,
                        pyplot as plt,
                        ticker,
                        transforms)
from matplotlib.colors import LinearSegmentedColormap
from mpl_toolkits.axes_grid1 import make_axes_locatable
from mpl_toolkits.basemap import Basemap, pyproj

from mintpy.objects import timeseriesKeyNames, timeseriesDatasetNames
from mintpy.objects.colors import *
from mintpy.utils import (ptime,
                          readfile,
                          network as pnet,
                          utils as ut)


min_figsize_single = 6.0       # default min size in inch, for single plot
max_figsize_single = 10.0      # default min size in inch, for single plot
# default size in inch, for multiple subplots
default_figsize_multi = [15.0, 8.0]
max_figsize_height = 8.0       # max figure size in vertical direction in inch


######################################### BasemapExt class begein ############################################
class BasemapExt(Basemap):
    """
    Extend Basemap class to add drawscale(), because Basemap.drawmapscale() do not support 'cyl' projection.
    """

    def draw_scale_bar(self, loc=[0.2, 0.2, 0.1], ax=None, labelpad=0.05, font_size=12, color='k'):
        """draw a simple map scale from x1,y to x2,y in map projection coordinates, label it with actual distance
        ref_link: http://matplotlib.1069221.n5.nabble.com/basemap-scalebar-td14133.html
        Parameters: loc : list of 3 float, distance, lat/lon of scale bar center in ratio of width, relative coord
                    ax  : matplotlib.pyplot.axes object
                    labelpad : float
        Example:    m.drawscale()
        """
        gc = pyproj.Geod(a=self.rmajor, b=self.rminor)

        # length in meter
        scene_width = gc.inv(self.lonmin, self.latmin, self.lonmax, self.latmin)[2]
        distance = ut.round_to_1(scene_width * loc[0])
        lon_c = self.lonmin + loc[1] * (self.lonmax - self.lonmin)
        lat_c = self.latmin + loc[2] * (self.latmax - self.latmin)

        # plot scale bar
        if distance > 1000.0:
            distance = np.rint(distance/1000.0)*1000.0
        lon_c2, lat_c2 = gc.fwd(lon_c, lat_c, 90, distance)[0:2]
        length = np.abs(lon_c - lon_c2)
        lon0 = lon_c - length/2.0
        lon1 = lon_c + length/2.0

        self.plot([lon0, lon1], [lat_c, lat_c], color=color)
        self.plot([lon0, lon0], [lat_c, lat_c + 0.1*length], color=color)
        self.plot([lon1, lon1], [lat_c, lat_c + 0.1*length], color=color)

        # plot scale bar label
        unit = 'm'
        if distance >= 1000.0:
            unit = 'km'
            distance *= 0.001
        label = '{:.0f} {}'.format(distance, unit)
        txt_offset = (self.latmax - self.latmin) * labelpad
        if not ax:
            ax = plt.gca()
        ax.text(lon0+0.5*length, lat_c+txt_offset, label,
                verticalalignment='center', horizontalalignment='center',
                fontsize=font_size, color=color)


    def draw_lalo_label(self, geo_box, ax=None, lalo_step=None, lalo_loc=[1, 0, 0, 1], lalo_max_num=4,
                        font_size=12, color='k', xoffset=None, yoffset=None, print_msg=True):
        """Auto draw lat/lon label/tick based on coverage from geo_box
        Parameters: geo_box : 4-tuple of float, defining UL_lon, UL_lat, LR_lon, LR_lat coordinate
                    ax      : axes object the labels are drawn
                    lalo_loc  : list of 4 bool, positions where the labels are drawn as in [left, right, top, bottom]
                                default: [1,0,0,1]
                    lalo_step : float
                    lalo_max_num : int
        Example:    geo_box = (128.0, 37.0, 138.0, 30.0)
                    m.draw_lalo_label(geo_box)
        """
        if isinstance(lalo_step, float):
            lalo_step = [lalo_step, lalo_step]
        lats, lons, lalo_step = self.auto_lalo_sequence(geo_box,
                                                        lalo_step=lalo_step,
                                                        lalo_max_num=lalo_max_num,
                                                        print_msg=print_msg)

        digit = np.int(np.floor(np.log10(lalo_step[0])))
        fmt = '%.'+'%d' % (abs(min(digit, 0)))+'f'
        # Change the 2 lines below for customized label
        #lats = np.linspace(31.55, 31.60, 2)
        #lons = np.linspace(130.60, 130.70, 3)

        # Plot x/y tick without label
        if not ax:
            ax = plt.gca()
        ax.tick_params(which='both', direction='in', labelsize=font_size,
                       bottom=True, top=True, left=True, right=True)

        ax.set_xticks(lons)
        ax.set_yticks(lats)
        ax.set_xticklabels([])
        ax.set_yticklabels([])
        # ax.xaxis.tick_top()

        # Plot x/y label
        labels_lat = np.multiply(lalo_loc, [1, 1, 0, 0])
        labels_lon = np.multiply(lalo_loc, [0, 0, 1, 1])
        self.drawparallels(lats, fmt=fmt, labels=labels_lat, linewidth=0.05,
                           fontsize=font_size, color=color, textcolor=color,
                           xoffset=xoffset, yoffset=yoffset)
        self.drawmeridians(lons, fmt=fmt, labels=labels_lon, linewidth=0.05,
                           fontsize=font_size, color=color, textcolor=color,
                           xoffset=xoffset, yoffset=yoffset)
        return

    def auto_lalo_sequence(self, geo_box, lalo_step=None, lalo_max_num=4, step_candidate=[1, 2, 3, 4, 5],
                           print_msg=True):
        """Auto calculate lat/lon label sequence based on input geo_box
        Parameters: geo_box        : 4-tuple of float, defining UL_lon, UL_lat, LR_lon, LR_lat coordinate
                    lalo_step      : float
                    lalo_max_num   : int, rough major tick number along the longer axis
                    step_candidate : list of int, candidate list for the significant number of step
        Returns:    lats/lons : np.array of float, sequence of lat/lon auto calculated from input geo_box
                    lalo_step : float, lat/lon label step
        Example:    geo_box = (128.0, 37.0, 138.0, 30.0)
                    lats, lons, step = m.auto_lalo_sequence(geo_box)
        """
        max_lalo_dist = max([geo_box[1]-geo_box[3], geo_box[2]-geo_box[0]])

        if not lalo_step:
            # Initial tick step
            lalo_step = ut.round_to_1(max_lalo_dist/lalo_max_num)

            # Final tick step - choose from candidate list
            digit = np.int(np.floor(np.log10(lalo_step)))
            lalo_step_candidate = [i*10**digit for i in step_candidate]
            distance = [(i - max_lalo_dist/lalo_max_num) ** 2
                        for i in lalo_step_candidate]
            lalo_step = lalo_step_candidate[distance.index(min(distance))]
            lalo_step = [lalo_step, lalo_step]
        if print_msg:
            print('label step in degree: {}'.format(lalo_step))

        # Auto tick sequence
        digit = np.int(np.floor(np.log10(lalo_step[0])))
        lat_major = np.ceil(geo_box[3]/10**(digit+1))*10**(digit+1)
        lats = np.unique(np.hstack((np.arange(lat_major, lat_major-10.*max_lalo_dist, -lalo_step[0]),
                                    np.arange(lat_major, lat_major+10.*max_lalo_dist, lalo_step[0]))))
        lats = np.sort(lats[np.where(np.logical_and(lats >= geo_box[3], lats <= geo_box[1]))])

        lon_major = np.ceil(geo_box[0]/10**(digit+1))*10**(digit+1)
        lons = np.unique(np.hstack((np.arange(lon_major, lon_major-10.*max_lalo_dist, -lalo_step[1]),
                                    np.arange(lon_major, lon_major+10.*max_lalo_dist, lalo_step[1]))))
        lons = np.sort(lons[np.where(np.logical_and(lons >= geo_box[0], lons <= geo_box[2]))])

        return lats, lons, lalo_step
######################################### BasemapExt class end ############################################


################################# SelectFromCollection class begin ########################################
class SelectFromCollection(object):
    """Select indices from a matplotlib collection using `PolygonSelector`.
    
    Selected pixels within the polygon is marked as True and saved in the 
    member variable self.mask, in the same size as input AxesImage object
    with all the other pixels marked as False.

    Parameters
    ----------
    ax : :class:`~matplotlib.axes.Axes`
        Axes to interact with.

    collection : :class:`matplotlib.collections.Collection` subclass
        Collection you want to select from.

    Examples
    --------
    import matplotlib.pyplot as plt
    from mintpy.utils import readfile, plot as pp
    
    fig, ax = plt.subplots()
    data = readfile.read('velocity.h5', datasetName='velocity')[0]
    im = ax.imshow(data)
    
    selector = pp.SelectFromCollection(ax, im)
    plt.show()
    selector.disconnect()
    
    plt.figure()
    plt.imshow(selector.mask)
    plt.show()
    """

    def __init__(self, ax, collection, alpha_other=0.3):
        from matplotlib.widgets import PolygonSelector
        self.canvas = ax.figure.canvas
        self.collection = collection
        self.prepare_coordinates()

        self.poly = PolygonSelector(ax, self.onselect)

        msg = "\nSelect points in the figure by enclosing them within a polygon.\n"
        msg += "Press the 'esc' key to start a new polygon.\n"
        msg += "Try hold to left key to move a single vertex.\n"
        msg += "After complete the selection, close the figure/window to continue.\n"
        print(msg)

    def prepare_coordinates(self):
        imgExt = self.collection.get_extent()
        self.length = int(imgExt[2] - imgExt[3])
        self.width  = int(imgExt[1] - imgExt[0])
        yy, xx = np.mgrid[:self.length, :self.width]
        self.coords = np.hstack((xx.reshape(-1, 1),
                                 yy.reshape(-1, 1)))

    def onselect(self, verts):
        from matplotlib.path import Path
        self.poly_path = Path(verts)
        self.mask = self.poly_path.contains_points(self.coords).reshape(self.length,
                                                                        self.width)
        self.canvas.draw_idle()

    def disconnect(self):
        self.poly.disconnect_events()
        self.canvas.draw_idle()

## Utility script
def get_poly_mask(data, print_msg=True):
    """Get mask of pixels within polygon from interactive selection
    Parameters: data : 2D np.array in size of (length, width)
    Returns:    mask : 2D np.arrat in size of (length, width) in np.bool_ format
    """
    fig, ax = plt.subplots()
    vlim = np.nanmax(np.abs(data))
    im = ax.imshow(data, cmap='jet', vmin=-vlim, vmax=vlim)
    fig.colorbar(im)

    selector = SelectFromCollection(ax, im)
    plt.show()
    selector.disconnect()

    if hasattr(selector, 'mask'):
        mask = selector.mask
        if print_msg:
            print('selected polygon: {}'.format(selector.poly_path))
    else:
        mask = None
        if print_msg:
            print('no polygon selected.\n')
    return mask
################################## SelectFromCollection class end #########################################



########################################### Parser utilities ##############################################
def cmd_line_parse(iargs=''):
    parser = argparse.ArgumentParser(description='Ploting Parser')
    parser = add_data_disp_argument(parser)
    parser = add_dem_argument(parser)
    parser = add_figure_argument(parser)
    parser = add_gps_argument(parser)
    parser = add_mask_argument(parser)
    parser = add_map_argument(parser)
    parser = add_point_argument(parser)
    parser = add_reference_argument(parser)
    parser = add_save_argument(parser)
    parser = add_subset_argument(parser)

    inps = parser.parse_args(args=iargs)
    return inps


def add_data_disp_argument(parser):
    # Data Display Option
    data = parser.add_argument_group('Data Display Options', 'Options to adjust the dataset display')
    data.add_argument('-v','--vlim', dest='vlim', nargs=2, metavar=('VMIN', 'VMAX'), type=float,
                      help='Display limits for matrix plotting.')
    data.add_argument('-u', '--unit', dest='disp_unit', metavar='UNIT',
                      help='unit for display.  Its priority > wrap')

    data.add_argument('--wrap', action='store_true',
                      help='re-wrap data to display data in fringes.')
    data.add_argument('--wrap-range', dest='wrap_range', type=float, nargs=2,
                      default=[-1.*np.pi, np.pi], metavar=('MIN', 'MAX'),
                      help='range of one cycle after wrapping, default: [-pi, pi]')

    data.add_argument('--flip-lr', dest='flip_lr',
                      action='store_true', help='flip left-right')
    data.add_argument('--flip-ud', dest='flip_ud',
                      action='store_true', help='flip up-down')
    data.add_argument('--noflip', dest='auto_flip', action='store_false',
                      help='turn off auto flip for radar coordinate file')

    data.add_argument('--multilook-num', dest='multilook_num', type=int, default=1, metavar='NUM',
                      help='multilook data in X and Y direction with a factor for display')
    data.add_argument('--nomultilook', '--no-multilook', dest='multilook', action='store_false',
                      help='do not multilook, for high quality display. \n'
                           'If multilook and multilook_num=1, multilook_num will be estimated automatically.\n'
                           'Useful when displaying big datasets.')
    data.add_argument('--alpha', dest='transparency', type=float,
                      help='Data transparency. \n'
                           '0.0 - fully transparent, 1.0 - no transparency.')
    return parser


def add_dem_argument(parser):
    # DEM
    dem = parser.add_argument_group('DEM', 'display topography in the background')
    dem.add_argument('-d', '--dem', dest='dem_file', metavar='DEM_FILE',
                     help='DEM file to show topography as background')
    dem.add_argument('--dem-noshade', dest='disp_dem_shade', action='store_false',
                     help='do not show DEM shaded relief')
    dem.add_argument('--dem-nocontour', dest='disp_dem_contour', action='store_false',
                     help='do not show DEM contour lines')
    dem.add_argument('--contour-smooth', dest='dem_contour_smooth', type=float, default=3.0,
                     help='Background topography contour smooth factor - sigma of Gaussian filter. \n'
                          'Default is 3.0; set to 0.0 for no smoothing.')
    dem.add_argument('--contour-step', dest='dem_contour_step', metavar='NUM', type=float, default=200.0,
                     help='Background topography contour step in meters. \n'
                          'Default is 200 meters.')
    dem.add_argument('--shade-az', dest='shade_azdeg', type=float, default=315., metavar='DEG',
                     help='The azimuth (0-360, degrees clockwise from North) of the light source\n'
                          'Default is 315.')
    dem.add_argument('--shade-alt', dest='shade_altdeg', type=float, default=45., metavar='DEG',
                     help='The altitude (0-90, degrees up from horizontal) of the light source.\n'
                          'Default is 45.')
    dem.add_argument('--shade-min', dest='shade_min', type=float, default=-4000., metavar='MIN',
                     help='The min height in m of colormap of shaded relief topography\n'
                          'Default: -4000 m')
    dem.add_argument('--shade-max', dest='shade_max', type=float, default=999., metavar='MAX',
                     help='The max height of colormap of shaded relief topography\n'
                          'Default: max(DEM) + 2000 m')
    dem.add_argument('--shade-exag', dest='shade_exag', type=float, default=0.5,
                     help='Vertical exaggeration ratio, default: 0.5')
    return parser


def add_figure_argument(parser):
    """Arguments for figure setting"""
    fig = parser.add_argument_group('Figure', 'Figure settings for display')
    fig.add_argument('--fontsize', dest='font_size',
                     type=int, help='font size')
    fig.add_argument('--fontcolor', dest='font_color',
                     default='k', help='font color')

    # axis format
    fig.add_argument('--nowhitespace', dest='disp_whitespace',
                     action='store_false', help='do not display white space')
    fig.add_argument('--noaxis', dest='disp_axis',
                     action='store_false', help='do not display axis')
    fig.add_argument('--notick', dest='disp_tick',
                     action='store_false', help='do not display tick in x/y axis')

    # colormap
    fig.add_argument('-c', '--colormap', dest='colormap',
                     help='colormap used for display, i.e. jet, RdBu, hsv, jet_r, temperature, viridis,  etc.\n'
                          'colormaps in Matplotlib - http://matplotlib.org/users/colormaps.html\n'
                          'colormaps in GMT - http://soliton.vm.bytemark.co.uk/pub/cpt-city/')
    fig.add_argument('--cm-lut', dest='cmap_lut', type=int, default=256, metavar='NUM',
                     help='number of increment of colormap lookup table')

    # colorbar
    fig.add_argument('--nocbar', '--nocolorbar', dest='disp_cbar',
                     action='store_false', help='do not display colorbar')
    fig.add_argument('--cbar-nbins', dest='cbar_nbins', metavar='NUM',
                     type=int, help='number of bins for colorbar')
    fig.add_argument('--cbar-ext', dest='cbar_ext', default=None,
                     choices={'neither', 'min', 'max', 'both', None},
                     help='Extend setting of colorbar; based on data stat by default.')
    fig.add_argument('--cbar-label', dest='cbar_label', default=None, help='colorbar label')
    fig.add_argument('--cbar-loc', dest='cbar_loc', type=str, default='right',
                     help='colorbar location for single plot')
    fig.add_argument('--cbar-size', dest='cbar_size', type=str, default="2%",
                     help='colorbar size and pad')

    # title
    fig.add_argument('--notitle', dest='disp_title',
                     action='store_false', help='do not display title')
    fig.add_argument('--title-in', dest='fig_title_in',
                     action='store_true', help='draw title in/out of axes')
    fig.add_argument('--figtitle', dest='fig_title',
                     help='Title shown in the figure.')

    # size, subplots number and space
    fig.add_argument('--figsize', dest='fig_size', metavar=('WID', 'LEN'), type=float, nargs=2,
                     help='figure size in inches - width and length')
    fig.add_argument('--dpi', dest='fig_dpi', metavar='DPI', type=int, default=300,
                     help='DPI - dot per inch - for display/write')
    fig.add_argument('--figext', dest='fig_ext',
                     default='.png', choices=['.emf', '.eps', '.pdf', '.png', '.ps', '.raw', '.rgba', '.svg', '.svgz'],
                     help='File extension for figure output file')
    fig.add_argument('--fignum', dest='fig_num', type=int, metavar='NUM',
                     help='number of figure windows')
    fig.add_argument('--nrows', dest='fig_row_num', type=int, default=1, metavar='NUM',
                     help='subplot number in row')
    fig.add_argument('--ncols', dest='fig_col_num', type=int, default=1, metavar='NUM',
                     help='subplot number in column')
    fig.add_argument('--wspace', dest='fig_wid_space', type=float,
                     help='width space between subplots in inches')
    fig.add_argument('--hspace', dest='fig_hei_space', type=float,
                     help='height space between subplots in inches')
    fig.add_argument('--no-tight-layout', dest='fig_tight_layout', action='store_false',
                     help='disable automatic tight layout for multiple subplots')
    fig.add_argument('--coord', dest='fig_coord', choices=['radar', 'geo'], default='geo',
                     help='Display in radar/geo coordination system, for geocoded file only.')
    fig.add_argument('--animation', action='store_true',
                     help='enable animation mode')

    return parser


def add_gps_argument(parser):
    gps = parser.add_argument_group('GPS', 'GPS data to display')
    gps.add_argument('--show-gps', dest='disp_gps', action='store_true',
                     help='Show UNR GPS location within the coverage.')
    gps.add_argument('--gps-label', dest='disp_gps_label', action='store_true',
                     help='Show GPS site name')
    gps.add_argument('--gps-comp', dest='gps_component', choices={'enu2los', 'hz2los', 'up2los'},
                     help='Plot GPS in color indicating deformation velocity direction')
    gps.add_argument('--ref-gps', dest='ref_gps_site', type=str, help='Reference GPS site')
    gps.add_argument('--gps-start-date', dest='gps_start_date', type=str, metavar='YYYYMMDD',
                     help='start date of GPS data, default is date of the 1st SAR acquisiton')
    gps.add_argument('--gps-end-date', dest='gps_end_date', type=str, metavar='YYYYMMDD',
                     help='start date of GPS data, default is date of the last SAR acquisiton')
    return parser


def add_mask_argument(parser):
    mask = parser.add_argument_group('Mask', 'Mask file/options')
    mask.add_argument('-m','--mask', dest='mask_file', metavar='FILE',
                      help='mask file for display')
    mask.add_argument('--zm','--zero-mask', dest='zero_mask', action='store_true',
                      help='mask pixels with zero value.')
    return parser


def add_map_argument(parser):
    # Map
    mapg = parser.add_argument_group('Map', 'Map settings for display')
    mapg.add_argument('--coastline', action='store_true', help='Draw coastline.')
    
    # lalo label
    mapg.add_argument('--lalo-loc', dest='lalo_loc', type=int, nargs=4, default=[1, 0, 0, 1],
                      metavar=('left', 'right', 'top', 'bottom'),
                      help='Draw lalo label in [left, right, top, bottom], default is [1,0,0,1]')
    mapg.add_argument('--lalo-label', dest='lalo_label', action='store_true',
                      help='Show N, S, E, W tick label for plot in geo-coordinate.\n'
                           'Useful for final figure output.')
    mapg.add_argument('--lalo-max-num', dest='lalo_max_num', type=int, default=4, metavar='NUM',
                      help='Maximum number of lalo tick label, 4 by default.')
    mapg.add_argument('--lalo-step', dest='lalo_step', metavar='DEG',
                      type=float, help='Lat/lon step for lalo-label option.')

    mapg.add_argument('--projection', dest='map_projection', default='cyl', metavar='NAME',
                      help='map projection when plotting in geo-coordinate. \n'
                           'Reference - http://matplotlib.org/basemap/users/mapsetup.html\n\n')
    mapg.add_argument('--resolution', default='c', choices={'c', 'l', 'i', 'h', 'f', None},
                      help='Resolution of boundary database to use.\n' +
                           'c (crude, default), l (low), i (intermediate), h (high), f (full) or None.')

    # scale bar
    mapg.add_argument('--scalebar', nargs=3, metavar=('LEN', 'X', 'Y'), type=float,
                      default=[0.2, 0.2, 0.1],
                      help='scale bar distance and location in ratio:\n' +
                           '\tdistance in ratio of total width\n' + 
                           '\tlocation in X/Y in ratio with respect to the lower left corner\n' + 
                           '--scalebar 0.2 0.2 0.1  #for lower left  corner\n' + 
                           '--scalebar 0.2 0.2 0.8  #for upper left  corner\n' + 
                           '--scalebar 0.2 0.8 0.1  #for lower right corner\n' + 
                           '--scalebar 0.2 0.8 0.8  #for upper right corner\n')
    mapg.add_argument('--noscalebar', '--nosbar', dest='disp_scalebar',
                      action='store_false', help='do not display scale bar.')
    mapg.add_argument('--scalebar-pad','--sbar-pad', dest='scalebar_pad', type=float,
                      default=0.05, help='scale bar label pad in ratio of scalebar width, default: 0.05')

    return parser


def add_point_argument(parser):
    pts = parser.add_argument_group('Point', 'Plot points defined by y/x or lat/lon')
    pts.add_argument('--pts-yx', dest='pts_yx', type=int, nargs='*', metavar=('Y', 'X'),
                     help='Point in (Y, X)')
    pts.add_argument('--pts-lalo', dest='pts_lalo', type=float, nargs='*', metavar=('LAT', 'LON'),
                     help='Point in (Lat, Lon)')
    pts.add_argument('--pts-file', dest='pts_file', type=str,
                     help='Point(s) defined in text file in lat/lon column')
    pts.add_argument('--pts-marker', dest='pts_marker', type=str, default='k^',
                     help='Marker of points of interest. Default: black triangle.')
    pts.add_argument('--pts-ms', dest='pts_marker_size', type=float, default=6.,
                     help='Marker size for points of interest. Default: 6.')
    return parser


def add_reference_argument(parser):
    ref = parser.add_argument_group('Reference', 'Show / Modify reference in time and space for display')
    # reference date
    ref.add_argument('--ref-date', dest='ref_date', metavar='DATE',
                     help='Change reference date for display')
    # reference pixel
    ref.add_argument('--ref-lalo', dest='ref_lalo', metavar=('LAT', 'LON'), type=float, nargs=2,
                     help='Change referene point LAT LON for display')
    ref.add_argument('--ref-yx', dest='ref_yx', metavar=('Y', 'X'), type=int, nargs=2,
                     help='Change referene point Y X for display')
    # reference pixel style
    ref.add_argument('--noreference', dest='disp_ref_pixel',
                     action='store_false', help='do not show reference point')
    ref.add_argument('--ref-marker', dest='ref_marker', default='ks',
                     help='marker of reference pixel')
    ref.add_argument('--ref-size', dest='ref_marker_size', metavar='NUM', type=int, default=6,
                     help='marker size of reference point, default: 10')
    return parser


def add_save_argument(parser):
    save = parser.add_argument_group('Save/Output', 'Save figure and write to file(s)')
    save.add_argument('-o', '--outfile', type=str, nargs='*', 
                      help="save the figure with assigned filename.\n"
                           "By default, it's calculated based on the input file name.")
    save.add_argument('--save', dest='save_fig', action='store_true',
                      help='save the figure')
    save.add_argument('--nodisplay', dest='disp_fig', action='store_false',
                      help='save and do not display the figure')
    save.add_argument('--update', dest='update_mode', action='store_true',
                      help='enable update mode for save figure: skip running if\n'+
                           '\t1) output file already exists\n'+
                           '\t2) output file is newer than input file.')
    return parser


def add_subset_argument(parser):
    # Subset
    sub = parser.add_argument_group('Subset', 'Display dataset in subset range')
    sub.add_argument('--sub-x','--subx', dest='subset_x', type=int, nargs=2, metavar=('XMIN', 'XMAX'),
                     help='subset display in x/cross-track/range direction')
    sub.add_argument('--sub-y','--suby', dest='subset_y', type=int, nargs=2, metavar=('YMIN', 'YMAX'),
                     help='subset display in y/along-track/azimuth direction')
    sub.add_argument('--sub-lat','--sublat', dest='subset_lat', type=float, nargs=2, metavar=('LATMIN', 'LATMAX'),
                     help='subset display in latitude')
    sub.add_argument('--sub-lon','--sublon', dest='subset_lon', type=float, nargs=2, metavar=('LONMIN', 'LONMAX'),
                     help='subset display in longitude')
    return parser


def read_point2inps(inps, coord_obj):
    if inps.pts_file and os.path.isfile(inps.pts_file):
        inps.pts_lalo = np.loadtxt(inps.pts_file, dtype=bytes).astype(float)
    if inps.pts_lalo is not None:
        inps.pts_lalo = np.array(inps.pts_lalo).reshape(-1, 2)
        inps.pts_yx = coord_obj.geo2radar(inps.pts_lalo[:, 0],
                                          inps.pts_lalo[:, 1],
                                          print_msg=False)
    if inps.pts_yx is not None:
        inps.pts_yx = np.array(inps.pts_yx).reshape(-1, 2)
    return inps


############################################ Plot Utilities #############################################
def add_inner_title(ax, title, loc, prop=None, **kwargs):
    from matplotlib.offsetbox import AnchoredText
    from matplotlib.patheffects import withStroke
    if prop is None:
        prop = dict(size=plt.rcParams['legend.fontsize'])
    at = AnchoredText(title, loc=loc, prop=prop,
                      pad=0., borderpad=0.5,
                      frameon=False, **kwargs)
    ax.add_artist(at)
    at.txt._text.set_path_effects([withStroke(foreground="w", linewidth=3)])
    return at


def auto_figure_size(shape, disp_cbar=False, ratio=1.0):
    """Get auto figure size based on input data shape"""
    length, width = shape
    plot_shape = [width*1.25, length]
    if not disp_cbar:
        plot_shape = [width, length]
    fig_scale = min(min_figsize_single/min(plot_shape),
                    max_figsize_single/max(plot_shape),
                    max_figsize_height/plot_shape[1])
    fig_size = [i*fig_scale*ratio for i in plot_shape]
    return fig_size


def auto_figure_title(fname, datasetNames=[], inps_dict=None):
    """Get auto figure title from meta dict and input options
    Parameters: fname : str, input file name
                datasetNames : list of str, optional, dataset to read for multi dataset/group files
                inps_dict : dict, optional, processing attributes, including:
                    ref_date
                    pix_box
                    wrap
    Returns:    fig_title : str, output figure title
    Example:    'geo_velocity.h5' = auto_figure_title('geo_velocity.h5', None, vars(inps))
                '101020-110220_ECMWF_demErr_quadratic' = auto_figure_title('timeseries_ECMWF_demErr_quadratic.h5', '110220')
    """
    if not datasetNames:
        datasetNames = []
    if isinstance(datasetNames, str):
        datesetNames = [datasetNames]

    atr = readfile.read_attribute(fname)
    k = atr['FILE_TYPE']
    num_pixel = int(atr['WIDTH']) * int(atr['LENGTH'])

    if k == 'ifgramStack':
        if len(datasetNames) == 1:
            fig_title = datasetNames[0]
            if 'unwCor' in fname:
                fig_title += '_unwCor'
        else:
            fig_title = datasetNames[0].split('-')[0]

    elif len(datasetNames) == 1 and k in timeseriesKeyNames:
        if 'ref_date' in inps_dict.keys():
            ref_date = inps_dict['ref_date']
        elif 'REF_DATE' in atr.keys():
            ref_date = atr['REF_DATE']
        else:
            ref_date = None

        if not ref_date:
            fig_title = datasetNames[0]
        else:
            fig_title = '{}_{}'.format(ref_date, datasetNames[0])

        try:
            ext = os.path.splitext(fname)[1]
            processMark = os.path.basename(fname).split(
                'timeseries')[1].split(ext)[0]
            fig_title += processMark
        except:
            pass
    elif k == 'geometry':
        if len(datasetNames) == 1:
            fig_title = datasetNames[0]
        elif datasetNames[0].startswith('bperp'):
            fig_title = 'bperp'
        else:
            fig_title = os.path.splitext(os.path.basename(fname))[0]
    else:
        fig_title = os.path.splitext(os.path.basename(fname))[0]

    if inps_dict.get('pix_box', None):
        box = inps_dict['pix_box']
        if (box[2] - box[0]) * (box[3] - box[1]) < num_pixel:
            fig_title += '_sub'

    if inps_dict.get('wrap', False):
        fig_title += '_wrap'
        wrap_range = inps_dict.get('wrap_range', [-1.*np.pi, np.pi])
        if (wrap_range[1] - wrap_range[0]) != 2*np.pi:
            fig_title += str(wrap_range[1] - wrap_range[0])

    return fig_title


def auto_flip_direction(metadata, ax=None, print_msg=True):
    """Check flip left-right and up-down based on attribute dict, for radar-coded file only"""
    # default value
    flip_lr = False
    flip_ud = False

    # auto flip for file in radar coordinates
    if 'Y_FIRST' not in metadata.keys() and 'ORBIT_DIRECTION' in metadata.keys():
        msg = '{} orbit'.format(metadata['ORBIT_DIRECTION'])
        if metadata['ORBIT_DIRECTION'].lower().startswith('a'):
            flip_ud = True
            msg += ' -> flip up-down'
        else:
            flip_lr = True
            msg += ' -> flip left-right'
        if print_msg:
            print(msg)

    if ax is not None:
        if flip_lr:
            ax.invert_xaxis()
        if flip_ud:
            ax.invert_yaxis()
        return ax

    return flip_lr, flip_ud


def auto_row_col_num(subplot_num, data_shape, fig_size, fig_num=1):
    """Get optimal row and column number given figure size number of subplots
    Parameters: subplot_num : int, total number of subplots
                data_shape : list of 2 float, data size in pixel in row and column direction of each plot
                fig_size : list of 2 float, figure window size in inches
                fig_num : int, number of figure windows, optional, default = 1.
    Returns:    row_num : number of subplots in row    direction per figure
                col_num : number of subplots in column direction per figure
    """
    subplot_num_per_fig = int(np.ceil(float(subplot_num) / float(fig_num)))

    data_shape_ratio = float(data_shape[0]) / float(data_shape[1])
    num_ratio = fig_size[1] / fig_size[0] / data_shape_ratio
    row_num = max(np.sqrt(subplot_num_per_fig * num_ratio), 1.)
    col_num = max(np.sqrt(subplot_num_per_fig / num_ratio), 1.)
    while np.rint(row_num) * np.rint(col_num) < subplot_num_per_fig:
        if row_num % 1 > col_num % 1:
            row_num += 0.5
        else:
            col_num += 0.5
    row_num = int(np.rint(row_num))
    col_num = int(np.rint(col_num))
    return row_num, col_num


def auto_shared_lalo_location(axs, loc=(1,0,0,1), flatten=False):
    """Return the auto lat/lon label location of subplots
    Parameters: axs : 2D np.ndarray of matplotlib.axes._subplots.AxesSubplot object
                loc : tuple of 4 bool, for (left, right, top, bottom)
                flatten : bool, return variable in 2D np.ndarray or in list of flattened array
    Returns:    locs : 2D np.ndarray of tuple of 4 bool.
    """
    nrows, ncols = axs.shape
    locs = np.zeros([nrows, ncols, 4], dtype=int)
    locs[ :, 0,0] = loc[0]
    locs[ :,-1,1] = loc[1]
    locs[ 0, :,2] = loc[2]
    locs[-1, :,3] = loc[3]

    if flatten:
        loc_list = list(locs.tolist())
        locs = []
        for i in range(nrows):
            for j in range(ncols):
                locs.append(loc_list[i][j])
    return locs


def check_colormap_input(metadata, cmap_name=None, datasetName=None, cmap_lut=256, print_msg=True):
    gray_dataset_key_words = ['coherence', 'temporal_coherence',
                              '.cor', '.mli', '.slc', '.amp', '.ramp']
    if not cmap_name:
        if any(i in gray_dataset_key_words for i in [metadata['FILE_TYPE'],
                                                     str(datasetName).split('-')[0]]):
            cmap_name = 'gray'
        else:
            cmap_name = 'jet'
    if print_msg:
        print('colormap:', cmap_name)

    return ColormapExt(cmap_name, cmap_lut).colormap


def auto_adjust_xaxis_date(ax, datevector, fontsize=12, every_year=1):
    """Adjust X axis
    Input:
        ax : matplotlib figure axes object
        datevector : list of float, date in years
                     i.e. [2007.013698630137, 2007.521917808219, 2007.6463470319634]
    Output:
        ax  - matplotlib figure axes object
        dss - datetime.datetime object, xmin
        dee - datetime.datetime object, xmax
    """
    # convert datetime.datetime format into date in years
    if isinstance(datevector[0], datetime.datetime):
        datevector = [i.year + (i.timetuple().tm_yday-1)/365.25 for i in datevector]

    # Min/Max
    ts = datevector[0]  - 0.2;  ys=int(ts);  ms=int((ts - ys) * 12.0)
    te = datevector[-1] + 0.3;  ye=int(te);  me=int((te - ye) * 12.0)
    if ms > 12:   ys = ys + 1;   ms = 1
    if me > 12:   ye = ye + 1;   me = 1
    if ms < 1:    ys = ys - 1;   ms = 12
    if me < 1:    ye = ye - 1;   me = 12
    dss = datetime.datetime(ys, ms, 1, 0, 0)
    dee = datetime.datetime(ye, me, 1, 0, 0)
    ax.set_xlim(dss, dee)

    # Label/Tick format
    ax.fmt_xdata = mdates.DateFormatter('%Y-%m-%d %H:%M:%S')
    ax.xaxis.set_major_locator(mdates.YearLocator(every_year))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_minor_locator(mdates.MonthLocator())

    # Label font size
    ax.tick_params(labelsize=fontsize)
    # fig2.autofmt_xdate()     #adjust x overlap by rorating, may enble again
    return ax, dss, dee


def auto_adjust_yaxis(ax, dataList, fontsize=12, ymin=None, ymax=None):
    """Adjust Y axis
    Input:
        ax       : matplot figure axes object
        dataList : list of float, value in y axis
        fontsize : float, font size
        ymin     : float, lower y axis limit
        ymax     : float, upper y axis limit
    Output:
        ax
    """
    # Min/Max
    dataRange = max(dataList) - min(dataList)
    if ymin is None:
        ymin = min(dataList) - 0.1*dataRange
    if ymax is None:
        ymax = max(dataList) + 0.1*dataRange
    ax.set_ylim([ymin, ymax])
    # Tick/Label setting
    #xticklabels = plt.getp(ax, 'xticklabels')
    #yticklabels = plt.getp(ax, 'yticklabels')
    #plt.setp(yticklabels, 'color', 'k', fontsize=fontsize)
    #plt.setp(xticklabels, 'color', 'k', fontsize=fontsize)

    return ax


####################################### Plot ################################################
def plot_coherence_history(ax, date12List, cohList, plot_dict={}):
    """Plot min/max Coherence of all interferograms for each date"""
    # Figure Setting
    if not 'fontsize'    in plot_dict.keys():   plot_dict['fontsize']    = 12
    if not 'linewidth'   in plot_dict.keys():   plot_dict['linewidth']   = 2
    if not 'markercolor' in plot_dict.keys():   plot_dict['markercolor'] = 'orange'
    if not 'markersize'  in plot_dict.keys():   plot_dict['markersize']  = 16
    if not 'disp_title'  in plot_dict.keys():   plot_dict['disp_title']  = True
    if not 'every_year'  in plot_dict.keys():   plot_dict['every_year']  = 1

    # Get date list
    date12List = ptime.yyyymmdd_date12(date12List)
    m_dates = [date12.split('_')[0] for date12 in date12List]
    s_dates = [date12.split('_')[1] for date12 in date12List]
    dateList = sorted(ptime.yyyymmdd(list(set(m_dates + s_dates))))

    dates, datevector = ptime.date_list2vector(dateList)
    bar_width = ut.most_common(np.diff(dates).tolist())*3/4
    x_list = [i-bar_width/2 for i in dates]

    coh_mat = pnet.coherence_matrix(date12List, cohList)

    ax.bar(x_list, np.nanmax(coh_mat, axis=0), bar_width.days, label='Max Coherence')
    ax.bar(x_list, np.nanmin(coh_mat, axis=0), bar_width.days, label='Min Coherence')

    if plot_dict['disp_title']:
        ax.set_title('Coherence History of All Related Interferograms')

    ax = auto_adjust_xaxis_date(ax, datevector, fontsize=plot_dict['fontsize'],
                                every_year=plot_dict['every_year'])[0]
    ax.set_ylim([0.0, 1.0])

    ax.set_xlabel('Time [years]', fontsize=plot_dict['fontsize'])
    ax.set_ylabel('Coherence', fontsize=plot_dict['fontsize'])
    ax.legend(loc='lower right')

    return ax


def plot_network(ax, date12List, dateList, pbaseList, plot_dict={}, date12List_drop=[], print_msg=True):
    """Plot Temporal-Perp baseline Network
    Inputs
        ax : matplotlib axes object
        date12List : list of string for date12 in YYYYMMDD_YYYYMMDD format
        dateList   : list of string, for date in YYYYMMDD format
        pbaseList  : list of float, perp baseline, len=number of acquisition
        plot_dict   : dictionary with the following items:
                      fontsize
                      linewidth
                      markercolor
                      markersize

                      cohList : list of float, coherence value of each interferogram, len = number of ifgrams
                      colormap : string, colormap name
                      disp_title : bool, show figure title or not, default: True
                      disp_drop: bool, show dropped interferograms or not, default: True
    Output
        ax : matplotlib axes object
    """

    # Figure Setting
    if not 'fontsize'    in plot_dict.keys():  plot_dict['fontsize']    = 12
    if not 'linewidth'   in plot_dict.keys():  plot_dict['linewidth']   = 2
    if not 'markercolor' in plot_dict.keys():  plot_dict['markercolor'] = 'orange'
    if not 'markersize'  in plot_dict.keys():  plot_dict['markersize']  = 16

    # For colorful display of coherence
    if not 'cohList'     in plot_dict.keys():  plot_dict['cohList']     = None
    if not 'ylabel'      in plot_dict.keys():  plot_dict['ylabel']      = 'Perp Baseline [m]'
    if not 'cbar_label'  in plot_dict.keys():  plot_dict['cbar_label']  = 'Average Spatial Coherence'
    if not 'disp_cbar'   in plot_dict.keys():  plot_dict['disp_cbar']   = True
    if not 'colormap'    in plot_dict.keys():  plot_dict['colormap']    = 'RdBu'
    if not 'cmap_vlist'  in plot_dict.keys():  plot_dict['cmap_vlist']  = [0.0, 0.4, 1.0]
    if not 'disp_title'  in plot_dict.keys():  plot_dict['disp_title']  = True
    if not 'disp_drop'   in plot_dict.keys():  plot_dict['disp_drop']   = True
    if not 'disp_legend' in plot_dict.keys():  plot_dict['disp_legend'] = True
    if not 'every_year'  in plot_dict.keys():  plot_dict['every_year']  = 1
    if not 'number'      in plot_dict.keys():  plot_dict['number']      = None

    # support input colormap: string for colormap name, or colormap object directly
    if isinstance(plot_dict['colormap'], str):
        cmap = ColormapExt(plot_dict['colormap']).colormap
    elif isinstance(plot_dict['colormap'], LinearSegmentedColormap):
        cmap = plot_dict['colormap']
    else:
        raise ValueError('unrecognized colormap input: {}'.format(plot_dict['colormap']))

    cohList = plot_dict['cohList']
    transparency = 0.7

    # Date Convert
    dateList = ptime.yyyymmdd(sorted(dateList))
    dates, datevector = ptime.date_list2vector(dateList)
    tbaseList = ptime.date_list2tbase(dateList)[0]

    ## maxBperp and maxBtemp
    date12List = ptime.yyyymmdd_date12(date12List)
    ifgram_num = len(date12List)
    pbase12 = np.zeros(ifgram_num)
    tbase12 = np.zeros(ifgram_num)
    for i in range(ifgram_num):
        m_date, s_date = date12List[i].split('_')
        m_idx = dateList.index(m_date)
        s_idx = dateList.index(s_date)
        pbase12[i] = pbaseList[s_idx] - pbaseList[m_idx]
        tbase12[i] = tbaseList[s_idx] - tbaseList[m_idx]
    if print_msg:
        print('max perpendicular baseline: {:.2f} m'.format(np.max(np.abs(pbase12))))
        print('max temporal      baseline: {} days'.format(np.max(tbase12)))

    ## Keep/Drop - date12
    date12List_keep = sorted(list(set(date12List) - set(date12List_drop)))
    idx_date12_keep = [date12List.index(i) for i in date12List_keep]
    idx_date12_drop = [date12List.index(i) for i in date12List_drop]
    if not date12List_drop:
        plot_dict['disp_drop'] = False

    ## Keep/Drop - date
    m_dates = [i.split('_')[0] for i in date12List_keep]
    s_dates = [i.split('_')[1] for i in date12List_keep]
    dateList_keep = ptime.yyyymmdd(sorted(list(set(m_dates + s_dates))))
    dateList_drop = sorted(list(set(dateList) - set(dateList_keep)))
    idx_date_keep = [dateList.index(i) for i in dateList_keep]
    idx_date_drop = [dateList.index(i) for i in dateList_drop]

    # Ploting
    if cohList is not None:
        data_min = min(cohList)
        data_max = max(cohList)
        disp_min = plot_dict['cmap_vlist'][0]
        disp_max = plot_dict['cmap_vlist'][-1]
        if print_msg:
            print('showing coherence')
            print('data range: {}'.format([data_min, data_max]))
            print('display range: {}'.format(plot_dict['cmap_vlist']))

        if plot_dict['disp_cbar']:
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", "3%", pad="3%")
            norm = mpl.colors.Normalize(vmin=disp_min, vmax=disp_max)
            cbar = mpl.colorbar.ColorbarBase(cax, cmap=cmap, norm=norm)
            cbar.ax.tick_params(labelsize=plot_dict['fontsize'])
            cbar.set_label(plot_dict['cbar_label'], fontsize=plot_dict['fontsize'])

        # plot low coherent ifgram first and high coherence ifgram later
        cohList_keep = [cohList[date12List.index(i)] for i in date12List_keep]
        date12List_keep = [x for _, x in sorted(zip(cohList_keep, date12List_keep))]

    # Dot - SAR Acquisition
    if idx_date_keep:
        x_list = [dates[i] for i in idx_date_keep]
        y_list = [pbaseList[i] for i in idx_date_keep]
        ax.plot(x_list, y_list, 'ko', alpha=0.7, ms=plot_dict['markersize'], mfc=plot_dict['markercolor'])
    if idx_date_drop:
        x_list = [dates[i] for i in idx_date_drop]
        y_list = [pbaseList[i] for i in idx_date_drop]
        ax.plot(x_list, y_list, 'ko', alpha=0.7, ms=plot_dict['markersize'], mfc='gray')

    ## Line - Pair/Interferogram
    # interferograms dropped
    if plot_dict['disp_drop']:
        for date12 in date12List_drop:
            date1, date2 = date12.split('_')
            idx1 = dateList.index(date1)
            idx2 = dateList.index(date2)
            x = np.array([dates[idx1], dates[idx2]])
            y = np.array([pbaseList[idx1], pbaseList[idx2]])
            if cohList is not None:
                coh = cohList[date12List.index(date12)]
                coh_norm = (coh - disp_min) / (disp_max - disp_min)
                ax.plot(x, y, '--', lw=plot_dict['linewidth'], alpha=transparency, c=cmap(coh_norm))
            else:
                ax.plot(x, y, '--', lw=plot_dict['linewidth'], alpha=transparency, c='k')

    # interferograms kept
    for date12 in date12List_keep:
        date1, date2 = date12.split('_')
        idx1 = dateList.index(date1)
        idx2 = dateList.index(date2)
        x = np.array([dates[idx1], dates[idx2]])
        y = np.array([pbaseList[idx1], pbaseList[idx2]])
        if cohList is not None:
            coh = cohList[date12List.index(date12)]
            coh_norm = (coh - disp_min) / (disp_max - disp_min)
            ax.plot(x, y, '-', lw=plot_dict['linewidth'], alpha=transparency, c=cmap(coh_norm))
        else:
            ax.plot(x, y, '-', lw=plot_dict['linewidth'], alpha=transparency, c='k')

    if plot_dict['disp_title']:
        ax.set_title('Interferogram Network', fontsize=plot_dict['fontsize'])

    # axis format
    ax = auto_adjust_xaxis_date(ax, datevector, fontsize=plot_dict['fontsize'],
                                every_year=plot_dict['every_year'])[0]
    ax = auto_adjust_yaxis(ax, pbaseList, fontsize=plot_dict['fontsize'])
    ax.set_xlabel('Time [years]', fontsize=plot_dict['fontsize'])
    ax.set_ylabel(plot_dict['ylabel'], fontsize=plot_dict['fontsize'])
    ax.tick_params(which='both', direction='in', labelsize=plot_dict['fontsize'],
                   bottom=True, top=True, left=True, right=True)

    if plot_dict['number'] is not None:
        ax.annotate(plot_dict['number'], xy=(0.03, 0.92), color='k',
                    xycoords='axes fraction', fontsize=plot_dict['fontsize'])

    # Legend
    if plot_dict['disp_drop'] and plot_dict['disp_legend']:
        solid_line = mlines.Line2D([], [], color='k', ls='solid',  label='Ifg used')
        dash_line  = mlines.Line2D([], [], color='k', ls='dashed', label='Ifg dropped')
        ax.legend(handles=[solid_line, dash_line])

    return ax


def plot_perp_baseline_hist(ax, dateList, pbaseList, plot_dict={}, dateList_drop=[]):
    """ Plot Perpendicular Spatial Baseline History
    Inputs
        ax : matplotlib axes object
        dateList : list of string, date in YYYYMMDD format
        pbaseList : list of float, perp baseline 
        plot_dict : dictionary with the following items:
                    fontsize
                    linewidth
                    markercolor
                    markersize
                    disp_title : bool, show figure title or not, default: True
                    every_year : int, number of years for the major tick on xaxis
        dateList_drop : list of string, date dropped in YYYYMMDD format
                          e.g. ['20080711', '20081011']
    Output:
        ax : matplotlib axes object
    """
    # Figure Setting
    if not 'fontsize'    in plot_dict.keys():   plot_dict['fontsize']    = 12
    if not 'linewidth'   in plot_dict.keys():   plot_dict['linewidth']   = 2
    if not 'markercolor' in plot_dict.keys():   plot_dict['markercolor'] = 'orange'
    if not 'markersize'  in plot_dict.keys():   plot_dict['markersize']  = 16
    if not 'disp_title'  in plot_dict.keys():   plot_dict['disp_title']  = True
    if not 'every_year'  in plot_dict.keys():   plot_dict['every_year']  = 1
    transparency = 0.7

    # Date Convert
    dateList = ptime.yyyymmdd(dateList)
    dates, datevector = ptime.date_list2vector(dateList)

    # Get index of date used and dropped
    # dateList_drop = ['20080711', '20081011']  # for debug
    idx_keep = list(range(len(dateList)))
    idx_drop = []
    for i in dateList_drop:
        idx = dateList.index(i)
        idx_keep.remove(idx)
        idx_drop.append(idx)

    # Plot
    # ax=fig.add_subplot(111)

    # Plot date used
    if idx_keep:
        x_list = [dates[i] for i in idx_keep]
        y_list = [pbaseList[i] for i in idx_keep]
        ax.plot(x_list, y_list, '-ko', alpha=transparency, lw=plot_dict['linewidth'],
                ms=plot_dict['markersize'], mfc=plot_dict['markercolor'])

    # Plot date dropped
    if idx_drop:
        x_list = [dates[i] for i in idx_drop]
        y_list = [pbaseList[i] for i in idx_drop]
        ax.plot(x_list, y_list, 'ko', alpha=transparency,
                ms=plot_dict['markersize'], mfc='gray')

    if plot_dict['disp_title']:
        ax.set_title('Perpendicular Baseline History', fontsize=plot_dict['fontsize'])

    # axis format
    ax = auto_adjust_xaxis_date(ax, datevector, fontsize=plot_dict['fontsize'],
                                every_year=plot_dict['every_year'])[0]
    ax = auto_adjust_yaxis(ax, pbaseList, fontsize=plot_dict['fontsize'])
    ax.set_xlabel('Time [years]', fontsize=plot_dict['fontsize'])
    ax.set_ylabel('Perpendicular Baseline [m]', fontsize=plot_dict['fontsize'])

    return ax

def plot_rotate_diag_coherence_matrix(ax, coh_list, date12_list, date12_list_drop=[],
                                      rotate_deg=-45., cmap='RdBu', disp_half=False, disp_min=0.2):
    """Plot Rotated Coherence Matrix, suitable for Sentinel-1 data with sequential network"""
    # support input colormap: string for colormap name, or colormap object directly
    if isinstance(cmap, str):
        cmap = ColormapExt(cmap).colormap
    elif isinstance(cmap, LinearSegmentedColormap):
        pass
    else:
        raise ValueError('unrecognized colormap input: {}'.format(plot_dict['colormap']))

    #calculate coherence matrix
    coh_mat = pnet.coherence_matrix(date12_list, coh_list)
    #for date12_list_drop, set value to nan in upper triangle
    if date12_list_drop:
        m_dates = [i.split('_')[0] for i in date12_list]
        s_dates = [i.split('_')[1] for i in date12_list]
        date_list = sorted(list(set(m_dates + s_dates)))
        for date12 in date12_list_drop:
            idx1, idx2 = [date_list.index(i) for i in date12.split('_')]
            coh_mat[idx2, idx1] = np.nan

    #aux info
    num_img = coh_mat.shape[0]
    idx1, idx2 = np.where(~np.isnan(coh_mat))
    num_conn = np.max(np.abs(idx1 - idx2))

    #plot diagonal - black
    diag_mat = np.diag(np.ones(num_img))
    diag_mat[diag_mat == 0.] = np.nan
    im = ax.imshow(diag_mat, cmap='gray_r', vmin=0.0, vmax=1.0)
    im.set_transform(transforms.Affine2D().rotate_deg(rotate_deg) + ax.transData)

    im = ax.imshow(coh_mat, vmin=disp_min, vmax=1, cmap=cmap)
    im.set_transform(transforms.Affine2D().rotate_deg(rotate_deg) + ax.transData)

    #axis format
    ymax = np.sqrt(num_conn**2 / 2.) + 0.9
    ax.set_xlim(-1, np.sqrt(num_img**2 * 2)-0.7)
    if disp_half:
        ax.set_ylim(0, ymax)
    else:
        ax.set_ylim(-1.*ymax, ymax)
    ax.get_xaxis().set_ticks([])
    ax.get_yaxis().set_ticks([])
    ax.axis('off')
    return ax, im


def plot_coherence_matrix(ax, date12List, cohList, date12List_drop=[], plot_dict={}):
    """Plot Coherence Matrix of input network
    if date12List_drop is not empty, plot KEPT pairs in the upper triangle and
                                           ALL  pairs in the lower triangle.
    Parameters: ax : matplotlib.pyplot.Axes,
                date12List : list of date12 in YYYYMMDD_YYYYMMDD format
                cohList    : list of float, coherence value
                date12List_drop : list of date12 for date12 marked as dropped
                plot_dict  : dict of plot settting
    Returns:    ax : matplotlib.pyplot.Axes
                coh_mat : 2D np.array in size of [num_date, num_date]
                im : mappable
    """
    # Figure Setting
    if not 'fontsize'    in plot_dict.keys():   plot_dict['fontsize']    = 12
    if not 'linewidth'   in plot_dict.keys():   plot_dict['linewidth']   = 2
    if not 'markercolor' in plot_dict.keys():   plot_dict['markercolor'] = 'orange'
    if not 'markersize'  in plot_dict.keys():   plot_dict['markersize']  = 16
    if not 'disp_title'  in plot_dict.keys():   plot_dict['disp_title']  = True
    if not 'fig_title'   in plot_dict.keys():   plot_dict['fig_title']   = 'Coherence Matrix'
    if not 'colormap'    in plot_dict.keys():   plot_dict['colormap']    = 'jet'
    if not 'cbar_label'  in plot_dict.keys():   plot_dict['cbar_label']  = 'Coherence'
    if not 'ylim'        in plot_dict.keys():   plot_dict['ylim']        = (0., 1.)
    if not 'disp_cbar'   in plot_dict.keys():   plot_dict['disp_cbar']   = True
    if not 'legend_loc'  in plot_dict.keys():   plot_dict['legend_loc']  = 'best'
    if not 'disp_legend' in plot_dict.keys():   plot_dict['disp_legend'] = True

    # support input colormap: string for colormap name, or colormap object directly
    if isinstance(plot_dict['colormap'], str):
        cmap = ColormapExt(plot_dict['colormap']).colormap
    elif isinstance(plot_dict['colormap'], LinearSegmentedColormap):
        cmap = plot_dict['colormap']
    else:
        raise ValueError('unrecognized colormap input: {}'.format(plot_dict['colormap']))

    date12List = ptime.yyyymmdd_date12(date12List)
    coh_mat = pnet.coherence_matrix(date12List, cohList)

    if date12List_drop:
        # Date Convert
        m_dates = [i.split('_')[0] for i in date12List]
        s_dates = [i.split('_')[1] for i in date12List]
        dateList = sorted(list(set(m_dates + s_dates)))
        # Set dropped pairs' value to nan, in upper triangle only.
        for date12 in date12List_drop:
            idx1, idx2 = [dateList.index(i) for i in date12.split('_')]
            coh_mat[idx1, idx2] = np.nan

    # Show diagonal value as black, to be distinguished from un-selected interferograms
    diag_mat = np.diag(np.ones(coh_mat.shape[0]))
    diag_mat[diag_mat == 0.] = np.nan
    im = ax.imshow(diag_mat, cmap='gray_r', vmin=0.0, vmax=1.0, interpolation='nearest')
    im = ax.imshow(coh_mat, cmap=cmap,
                   vmin=plot_dict['cmap_vlist'][0],
                   vmax=plot_dict['cmap_vlist'][-1],
                   interpolation='nearest')

    date_num = coh_mat.shape[0]
    if date_num < 30:    tick_step = 5
    elif date_num < 50:  tick_step = 10
    elif date_num < 100: tick_step = 20
    else:                tick_step = 30
    tick_list = list(range(0, date_num, tick_step))
    ax.get_xaxis().set_ticks(tick_list)
    ax.get_yaxis().set_ticks(tick_list)
    ax.set_xlabel('Image Number', fontsize=plot_dict['fontsize'])
    ax.set_ylabel('Image Number', fontsize=plot_dict['fontsize'])
    ax.tick_params(which='both', direction='in', labelsize=plot_dict['fontsize'],
                   bottom=True, top=True, left=True, right=True)

    if plot_dict['disp_title']:
        ax.set_title(plot_dict['fig_title'])

    # Colorbar
    if plot_dict['disp_cbar']:
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", "3%", pad="3%")
        cbar = plt.colorbar(im, cax=cax)
        cbar.set_label(plot_dict['cbar_label'], fontsize=plot_dict['fontsize'])

    # Legend
    if date12List_drop and plot_dict['disp_legend']:
        ax.plot([], [], label='Upper: Ifgrams used')
        ax.plot([], [], label='Lower: Ifgrams all')
        ax.legend(loc=plot_dict['legend_loc'], handlelength=0)

    return ax, coh_mat, im


def read_dem(dem_file, pix_box=None, geo_box=None, print_msg=True):
    if print_msg:
        print('reading DEM: {} ...'.format(os.path.basename(dem_file)))

    dem_metadata = readfile.read_attribute(dem_file)
    # read dem data
    if dem_metadata['FILE_TYPE'] == 'geometry':
        dsName = 'height'
    else:
        dsName = None

    # get dem_pix_box
    coord = ut.coordinate(dem_metadata)
    if pix_box is None:
        pix_box = (0, 0, int(dem_metadata['WIDTH']), int(dem_metadata['LENGTH']))

    # Support DEM with different Resolution and Coverage
    if geo_box:
        dem_pix_box = coord.box_geo2pixel(geo_box)
    else:
        dem_pix_box = pix_box
    box2read = coord.check_box_within_data_coverage(dem_pix_box, print_msg=False)

    dem, dem_metadata = readfile.read(dem_file,
                                      datasetName=dsName,
                                      box=box2read,
                                      print_msg=print_msg)

    # if input DEM does not cover the entire AOI, fill with NaN
    if pix_box is not None and box2read != dem_pix_box:
        if print_msg:
            print('align DEM to the input data file')
        dem_tmp = np.zeros((dem_pix_box[3] - dem_pix_box[1],
                            dem_pix_box[2] - dem_pix_box[0]), dtype=dem.dtype) * np.nan
        dem_tmp[box2read[1]-dem_pix_box[1]:box2read[3]-dem_pix_box[1],
                box2read[0]-dem_pix_box[0]:box2read[2]-dem_pix_box[0]] = dem
        dem = np.array(dem_tmp)
    return dem, dem_metadata, dem_pix_box


def prepare_dem_background(dem, inps=None, print_msg=True):
    """Prepare to plot DEM on background
    Parameters: dem : 2D np.int16 matrix, dem data
                inps : Namespace with the following 4 items:
                    'disp_dem_shade'    : bool,  True/False
                    'disp_dem_contour'  : bool,  True/False
                    'dem_contour_step'  : float, 200.0
                    'dem_contour_smooth': float, 3.0
    Returns:    dem_shade : 3D np.array in size of (length, width, 4)
                dem_contour : 2D np.array in size of (length, width)
                dem_contour_sequence : 1D np.array
    Examples:   dem = readfile.read('inputs/geometryRadar.h5')[0]
                dem_shade, dem_contour, dem_contour_seq = pp.prepare_dem_background(dem=dem)
    """
    # default returns
    dem_shade = None
    dem_contour = None
    dem_contour_sequence = None

    # default inputs
    if inps is None:
        inps = cmd_line_parse()
    if inps.shade_max == 999.:
        inps.shade_max = np.nanmax(dem) + 2000

    # prepare shade relief
    if inps.disp_dem_shade:
        from matplotlib.colors import LightSource
        ls = LightSource(azdeg=inps.shade_azdeg, altdeg=inps.shade_altdeg)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            dem_shade = ls.shade(dem, vert_exag=inps.shade_exag,
                                 cmap=ColormapExt('gray').colormap,
                                 vmin=inps.shade_min,
                                 vmax=inps.shade_max)
        dem_shade[np.isnan(dem_shade[:, :, 0])] = np.nan
        if print_msg:
            print('show shaded relief DEM')

    # prepare contour
    if inps.disp_dem_contour:
        from scipy import ndimage
        dem_contour = ndimage.gaussian_filter(dem, sigma=inps.dem_contour_smooth, order=0)
        dem_contour_sequence = np.arange(inps.dem_contour_step, 9000, step=inps.dem_contour_step)
        if print_msg:
            print(('show contour in step of {} m '
                   'with smoothing factor of {}').format(inps.dem_contour_step,
                                                         inps.dem_contour_smooth))
    return dem_shade, dem_contour, dem_contour_sequence


def plot_dem_background(ax, geo_box=None, dem_shade=None, dem_contour=None, dem_contour_seq=None,
                        dem=None, inps=None, print_msg=True):
    """Plot DEM as background.
    Parameters: ax : matplotlib.pyplot.Axes or BasemapExt object
                geo_box : tuple of 4 float in order of (E, N, W, S), geo bounding box
                dem_shade : 3D np.array in size of (length, width, 4)
                dem_contour : 2D np.array in size of (length, width)
                dem_contour_sequence : 1D np.array
                dem : 2D np.array of DEM data
                inps : Namespace with the following 4 items:
                    'disp_dem_shade'    : bool,  True/False
                    'disp_dem_contour'  : bool,  True/False
                    'dem_contour_step'  : float, 200.0
                    'dem_contour_smooth': float, 3.0
                    'pix_box'           : 4-tuple of int, (x0, y0, x1, y1)
    Returns:    ax : matplotlib.pyplot.Axes or BasemapExt object
    Examples:   m = pp.plot_dem_background(m, geo_box=inps.geo_box, dem=dem, inps=inps)
                ax = pp.plot_dem_background(ax=ax, geo_box=None, dem_shade=dem_shade,
                                            dem_contour=dem_contour, dem_contour_seq=dem_contour_seq)
    """
    # default inputs
    if inps is None:
        inps = cmd_line_parse()

    if all(i is None for i in [dem_shade, dem_contour, dem_contour_seq]) and dem is not None:
        (dem_shade,
         dem_contour,
         dem_contour_seq) = prepare_dem_background(dem, inps=inps, print_msg=print_msg)

    # get extent
    if hasattr(inps, 'pix_box'):
        pix_box = tuple(inps.pix_box)
    else:
        data = [i for i in [dem, dem_shade, dem_contour] if i is not None][0]
        pix_box = (0, 0, data.shape[1], data.shape[0])
    extent = (pix_box[0]-0.5, pix_box[2]-0.5,
              pix_box[3]-0.5, pix_box[1]-0.5) #(left, right, bottom, top) in data coordinates

    if dem_shade is not None:
        # geo coordinates
        if isinstance(ax, BasemapExt) and geo_box is not None:
            ax.imshow(dem_shade, interpolation='spline16', origin='upper', zorder=0)
        # radar coordinates
        elif isinstance(ax, plt.Axes):
            ax.imshow(dem_shade, interpolation='spline16', extent=extent, zorder=0)

    if dem_contour is not None and dem_contour_seq is not None:
        # geo coordinates
        if isinstance(ax, BasemapExt) and geo_box is not None:
            yy, xx = np.mgrid[geo_box[1]:geo_box[3]:dem_contour.shape[0]*1j,
                              geo_box[0]:geo_box[2]:dem_contour.shape[1]*1j]
            ax.contour(xx, yy, dem_contour, dem_contour_seq, origin='upper', linewidths=0.5,
                       colors='black', alpha=0.5, latlon='FALSE', zorder=1)
        # radar coordinates
        elif isinstance(ax, plt.Axes):
            ax.contour(dem_contour, dem_contour_seq, origin='upper',
                       colors='black', alpha=0.5, extent=extent, zorder=1)
    return ax


def plot_gps(ax, SNWE, inps, metadata=dict(), print_msg=True):
    from mintpy.objects.gps import search_gps, GPS
    marker_size = 7
    vmin, vmax = inps.vlim
    if isinstance(inps.colormap, str):
        cmap = ColormapExt(inps.colormap).colormap
    else:
        cmap = inps.colormap

    atr = dict(metadata)
    atr['UNIT'] = 'm'
    unit_fac = scale_data2disp_unit(metadata=atr, disp_unit=inps.disp_unit)[2]

    if not inps.gps_start_date:
        inps.gps_start_date = metadata.get('START_DATE', None)

    if not inps.gps_end_date:
        inps.gps_end_date = metadata.get('END_DATE', None)

    site_names, site_lats, site_lons = search_gps(SNWE, inps.gps_start_date, inps.gps_end_date)
    num_site = len(site_names)

    k = metadata['FILE_TYPE']
    if inps.gps_component and k not in ['velocity', 'timeseries']:
        inps.gps_component = None
        print('--gps-comp is not implemented for {} file yet, set --gps-comp = None and continue'.format(k))

    if inps.gps_component:
        if print_msg:
            print('-'*30)
            msg = 'calculating GPS '
            if k == 'velocity':
                msg += 'velocity'
            elif k == 'timeseries':
                msg += 'displacement'
            msg += ' with respect to {} in {} direction ...'.format(inps.ref_gps_site, inps.gps_component)
            print(msg)
            print('start date: {}'.format(inps.gps_start_date))
            print('end   date: {}'.format(inps.gps_end_date))
            prog_bar = ptime.progressBar(maxValue=num_site)

        # get insar_obj (meta / geom_file)
        geom_file = ut.get_geometry_file(['incidenceAngle','azimuthAngle'],
                                         work_dir=os.path.dirname(inps.file),
                                         coord='geo')
        if geom_file:
            geom_obj = geom_file
            print('use incidenceAngle/azimuthAngle from file: {}'.format(os.path.basename(geom_file)))
        else:
            geom_obj = metadata
            print('use incidenceAngle/azimuthAngle calculated from metadata')
        
        for i in range(num_site):
            obj = GPS(site_names[i])
            # calculate gps data value
            if k == 'velocity':
                gps_data = obj.get_gps_los_velocity(geom_obj,
                                                    start_date=inps.gps_start_date,
                                                    end_date=inps.gps_end_date,
                                                    ref_site=inps.ref_gps_site,
                                                    gps_comp=inps.gps_component) * unit_fac
            elif k == 'timeseries':
                dis = obj.read_gps_los_displacement(geom_obj,
                                                    start_date=inps.gps_start_date,
                                                    end_date=inps.gps_end_date,
                                                    ref_site=inps.ref_gps_site,
                                                    gps_comp=inps.gps_component)[1] * unit_fac
                gps_data = dis[-1] - dis[0]
            if print_msg:
                prog_bar.update(i+1, suffix=site_names[i])

            # plot
            if not gps_data:
                color = 'none'
            else:
                cm_idx = (gps_data - vmin) / (vmax - vmin)
                color = cmap(cm_idx)
            ax.scatter(site_lons[i], site_lats[i], color=color,
                       s=marker_size**2, edgecolors='k', zorder=10)
        if print_msg:
            prog_bar.close()
    else:
        ax.scatter(site_lons, site_lats, s=marker_size**2, color='w', edgecolors='k', zorder=10)

    # plot GPS label
    if inps.disp_gps_label:
        for i in range(len(site_names)):
            ax.annotate(site_names[i], xy=(site_lons[i], site_lats[i]),
                        fontsize=inps.font_size)
    return ax


def plot_colorbar(inps, im, cax):
    # Colorbar Extend
    if not inps.cbar_ext:
        if   inps.vlim[0] <= inps.dlim[0] and inps.vlim[1] >= inps.dlim[1]: inps.cbar_ext='neither'
        elif inps.vlim[0] >  inps.dlim[0] and inps.vlim[1] >= inps.dlim[1]: inps.cbar_ext='min'
        elif inps.vlim[0] <= inps.dlim[0] and inps.vlim[1] <  inps.dlim[1]: inps.cbar_ext='max'
        else:  inps.cbar_ext='both'

    if inps.cbar_loc in ['left', 'right']:
        orientation = 'vertical'
    else:
        orientation = 'horizontal'

    if inps.wrap and (inps.wrap_range[1] - inps.wrap_range[0]) == 2.*np.pi:
        cbar = plt.colorbar(im, cax=cax, ticks=[inps.wrap_range[0], 0, inps.wrap_range[1]],
                            orientation=orientation)
        cbar.ax.set_yticklabels([r'-$\pi$', '0', r'$\pi$'])
    else:
        cbar = plt.colorbar(im, cax=cax, extend=inps.cbar_ext, orientation=orientation)

    if inps.cbar_nbins:
        cbar.locator = ticker.MaxNLocator(nbins=inps.cbar_nbins)
        cbar.update_ticks()

    cbar.ax.tick_params(which='both', direction='out',
                        labelsize=inps.font_size, colors=inps.font_color)

    if not inps.cbar_label:
        cbar.set_label(inps.disp_unit, fontsize=inps.font_size, color=inps.font_color)
    else:
        cbar.set_label(inps.cbar_label, fontsize=inps.font_size, color=inps.font_color)
    return inps, cbar


def set_shared_ylabel(axes_list, label, labelpad=0.01, font_size=12, position='left'):
    """Set a y label shared by multiple axes
    Parameters: axes_list : list of axes in left/right most col direction
                label : string
                labelpad : float, Sets the padding between ticklabels and axis label
                font_size : int
                position : string, 'left' or 'right'
    """

    f = axes_list[0].get_figure()
    f.canvas.draw() #sets f.canvas.renderer needed below

    # get the center position for all plots
    top = axes_list[0].get_position().y1
    bottom = axes_list[-1].get_position().y0

    # get the coordinates of the left side of the tick labels 
    x0 = 1
    x1 = 0
    for ax in axes_list:
        ax.set_ylabel('') # just to make sure we don't and up with multiple labels
        bboxes = ax.yaxis.get_ticklabel_extents(f.canvas.renderer)[0]
        bboxes = bboxes.inverse_transformed(f.transFigure)
        x0t = bboxes.x0
        if x0t < x0:
            x0 = x0t
        x1t = bboxes.x1
        if x1t > x1:
            x1 = x1t
    tick_label_left = x0
    tick_label_right = x1

    # set position of label
    axes_list[-1].set_ylabel(label, fontsize=font_size)
    if position == 'left':
        axes_list[-1].yaxis.set_label_coords(tick_label_left - labelpad,
                                             (bottom + top)/2,
                                             transform=f.transFigure)
    else:
        axes_list[-1].yaxis.set_label_coords(tick_label_right + labelpad,
                                             (bottom + top)/2,
                                             transform=f.transFigure)
    return


def set_shared_xlabel(axes_list, label, labelpad=0.01, font_size=12, position='top'):
    """Set a y label shared by multiple axes
    Parameters: axes_list : list of axes in top/bottom row direction
                label : string
                labelpad : float, Sets the padding between ticklabels and axis label
                font_size : int
                position : string, 'top' or 'bottom'
    Example:    pp.set_shared_xlabel([ax1, ax2, ax3], 'Range (Pix.)')
    """

    f = axes_list[0].get_figure()
    f.canvas.draw() #sets f.canvas.renderer needed below

    # get the center position for all plots
    left = axes_list[0].get_position().x0
    right = axes_list[-1].get_position().x1

    # get the coordinates of the left side of the tick labels 
    y0 = 1
    y1 = 0
    for ax in axes_list:
        ax.set_xlabel('') # just to make sure we don't and up with multiple labels
        bboxes = ax.yaxis.get_ticklabel_extents(f.canvas.renderer)[0]
        bboxes = bboxes.inverse_transformed(f.transFigure)
        y0t = bboxes.y0
        if y0t < y0:
            y0 = y0t
        y1t = bboxes.y1
        if y1t > y1:
            y1 = y1t
    tick_label_bottom = y0
    tick_label_top = y1

    # set position of label
    axes_list[-1].set_xlabel(label, fontsize=font_size)
    if position == 'top':
        axes_list[-1].xaxis.set_label_coords((left + right) / 2,
                                             tick_label_top + labelpad,
                                             transform=f.transFigure)
    else:
        axes_list[-1].xaxis.set_label_coords((left + right) / 2,
                                             tick_label_bottom - labelpad,
                                             transform=f.transFigure)
    return


##################### Data Scale based on Unit and Wrap Range ##################
def check_disp_unit_and_wrap(metadata, disp_unit=None, wrap=False, wrap_range=[-1.*np.pi, np.pi], print_msg=True):
    """Get auto disp_unit for input dataset
    Example:
        if not inps.disp_unit:
            inps.disp_unit = pp.auto_disp_unit(atr)
    """
    # default display unit if not given
    if not disp_unit:
        k = metadata['FILE_TYPE']
        disp_unit = metadata['UNIT'].lower()
        if (k in ['timeseries', 'giantTimeseries', 'velocity', 'HDFEOS']
                and disp_unit.split('/')[0].endswith('m')):
            disp_unit = 'cm'
        elif k in ['.mli', '.slc', '.amp']:
            disp_unit = 'dB'

    if wrap:
        # wrap is supported for displacement file types only
        if disp_unit.split('/')[0] not in ['radian', 'm', 'cm', 'mm', '1']:
            wrap = False
            print('WARNING: re-wrap is disabled for disp_unit = {}'.format(disp_unit))
        elif disp_unit.split('/')[0] != 'radian' and (wrap_range[1] - wrap_range[0]) == 2.*np.pi:
            disp_unit = 'radian'
            if print_msg:
                print('change disp_unit = radian due to rewrapping')

    return disp_unit, wrap


def scale_data2disp_unit(data=None, metadata=dict(), disp_unit=None):
    """Scale data based on data unit and display unit
    Inputs:
        data    : 2D np.array
        metadata  : dictionary, meta data
        disp_unit : str, display unit
    Outputs:
        data    : 2D np.array, data after scaling
        disp_unit : str, display unit
    Default data file units in MintPy are:  m, m/yr, radian, 1
    """
    if not metadata:
        metadata['UNIT'] = 'm'

    # Initial
    scale = 1.0
    data_unit = metadata['UNIT'].lower().split('/')
    disp_unit = disp_unit.lower().split('/')

    # if data and display unit is the same
    if disp_unit == data_unit:
        return data, metadata['UNIT'], scale

    # Calculate scaling factor  - 1
    # phase unit - length / angle
    if data_unit[0].endswith('m'):
        if   disp_unit[0] == 'mm': scale *= 1000.0
        elif disp_unit[0] == 'cm': scale *= 100.0
        elif disp_unit[0] == 'dm': scale *= 10.0
        elif disp_unit[0] == 'm' : scale *= 1.0
        elif disp_unit[0] == 'km': scale *= 1/1000.0
        elif disp_unit[0] in ['radians','radian','rad','r']:
            range2phase = -(4*np.pi) / float(metadata['WAVELENGTH'])
            scale *= range2phase
        else:
            print('Unrecognized display phase/length unit:', disp_unit[0])
            return data, data_unit, scale

        if   data_unit[0] == 'mm': scale *= 0.001
        elif data_unit[0] == 'cm': scale *= 0.01
        elif data_unit[0] == 'dm': scale *= 0.1
        elif data_unit[0] == 'km': scale *= 1000.

    elif data_unit[0] == 'radian':
        phase2range = -float(metadata['WAVELENGTH']) / (4*np.pi)
        if   disp_unit[0] == 'mm': scale *= phase2range * 1000.0
        elif disp_unit[0] == 'cm': scale *= phase2range * 100.0
        elif disp_unit[0] == 'dm': scale *= phase2range * 10.0
        elif disp_unit[0] == 'm' : scale *= phase2range * 1.0
        elif disp_unit[0] == 'km': scale *= phase2range * 1/1000.0
        elif disp_unit[0] in ['radians','radian','rad','r']:
            pass
        else:
            print('Unrecognized phase/length unit:', disp_unit[0])
            return data, data_unit, scale

    # amplitude/coherence unit - 1
    elif data_unit[0] == '1':
        if disp_unit[0] == 'db' and data is not None:
            ind = np.nonzero(data)
            data[ind] = 10*np.log10(np.absolute(data[ind]))
            disp_unit[0] = 'dB'
        else:
            try:
                scale /= float(disp_unit[0])
            except:
                print('Un-scalable display unit:', disp_unit[0])
    else:
        print('Un-scalable data unit:', data_unit)

    # Calculate scaling factor  - 2
    if len(data_unit) == 2:
        try:
            disp_unit[1]
            if   disp_unit[1] in ['y','yr','year'  ]: disp_unit[1] = 'year'
            elif disp_unit[1] in ['m','mon','month']: disp_unit[1] = 'mon'; scale *= 12.0
            elif disp_unit[1] in ['d','day'        ]: disp_unit[1] = 'day'; scale *= 365.25
            else: print('Unrecognized time unit for display:', disp_unit[1])
        except:
            disp_unit.append('year')
        disp_unit = disp_unit[0]+'/'+disp_unit[1]
    else:
        disp_unit = disp_unit[0]

    # Scale input data
    if data is not None:
        data *= scale
    return data, disp_unit, scale


def scale_data4disp_unit_and_rewrap(data, metadata, disp_unit=None, wrap=False, wrap_range=[-1.*np.pi, np.pi],
                                    print_msg=True):
    """Scale 2D matrix value according to display unit and re-wrapping flag
    Inputs:
        data - 2D np.array
        metadata  - dict, including the following attributes:
               UNIT
               FILE_TYPE
               WAVELENGTH
        disp_unit  - string, optional
        wrap - bool, optional
    Outputs:
        data
        disp_unit
        wrap
    """
    if not disp_unit:
        disp_unit, wrap = check_disp_unit_and_wrap(metadata,
                                                   disp_unit=None,
                                                   wrap=wrap,
                                                   wrap_range=wrap_range, 
                                                   print_msg=print_msg)

    # Data Operation - Scale to display unit
    disp_scale = 1.0
    if not disp_unit == metadata['UNIT']:
        data, disp_unit, disp_scale = scale_data2disp_unit(data,
                                                           metadata=metadata,
                                                           disp_unit=disp_unit)

    # Data Operation - wrap
    if wrap:
        data = wrap_range[0] + np.mod(data - wrap_range[0], wrap_range[1] - wrap_range[0])
        if print_msg:
            print('re-wrapping data to {}'.format(wrap_range))
    return data, disp_unit, disp_scale, wrap


def read_mask(fname, mask_file=None, datasetName=None, box=None, print_msg=True):
    """Find and read mask for input data file fname
    Parameters: fname       : string, data file name/path
                mask_file   : string, optional, mask file name
                datasetName : string, optional, dataset name for HDFEOS file type
                box         : tuple of 4 int, for reading part of data
    Returns:    msk         : 2D np.array, mask data
                mask_file   : string, file name of mask data
    """
    atr = readfile.read_attribute(fname)
    k = atr['FILE_TYPE']
    # default mask file:
    if (not mask_file 
            and k in ['velocity', 'timeseries'] 
            and 'masked' not in fname):
        mask_file = 'maskTempCoh.h5'
        if 'PhaseVelocity' in fname:
            mask_file = None #'maskSpatialCoh.h5'
        # check coordinate
        if os.path.basename(fname).startswith('geo_'):
            mask_file = 'geo_{}'.format(mask_file)
        # absolute path and file existence
        mask_file = os.path.join(os.path.dirname(fname), str(mask_file))
        if not os.path.isfile(mask_file):
            mask_file = None

    # Read mask file if inputed
    msk = None
    if os.path.isfile(str(mask_file)):
        try:
            atrMsk = readfile.read_attribute(mask_file)
            if atrMsk['LENGTH'] == atr['LENGTH'] and atrMsk['WIDTH'] == atr['WIDTH']:
                msk = readfile.read(mask_file, box=box, print_msg=print_msg)[0]
                if print_msg:
                    print('read mask from file:', os.path.basename(mask_file))
            else:
                mask_file = None
                if print_msg:
                    print('WARNING: input file has different size from mask file: {}'.format(mask_file))
                    print('    Continue without mask')
        except:
            mask_file = None
            if print_msg:
                print('Can not open mask file:', mask_file)

    elif k in ['HDFEOS']:
        if datasetName.split('-')[0] in timeseriesDatasetNames:
            mask_file = fname
            msk = readfile.read(fname, datasetName='mask', print_msg=print_msg)[0]
            if print_msg:
                print('read {} contained mask dataset.'.format(k))

    elif fname.endswith('PARAMS.h5'):
        mask_file = fname
        h5msk = h5py.File(fname, 'r')
        msk = h5msk['cmask'][:] == 1.
        h5msk.close()
        if print_msg:
            print('read {} contained cmask dataset'.format(os.path.basename(fname)))
    return msk, mask_file

