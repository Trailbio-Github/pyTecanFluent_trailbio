from __future__ import print_function
# import
## batteries
import os
import sys
import argparse
import functools
from itertools import product
## 3rd party
import numpy as np
import pandas as pd
## package
from pyTecanFluent import Utils
from pyTecanFluent import Fluent
from pyTecanFluent import Labware

# functions
def get_desc():
    desc = 'Create robot commands for pooling samples'
    return desc

def parse_args(test_args=None, subparsers=None):
    # desc
    desc = get_desc()
    epi = """DESCRIPTION:
    Create a worklist and labware file for the TECAN Fluent robot for pooling 
    samples (eg., pooling PCR reaction replicates). 

    The main input is >=1 Excel or tab-delimited file containing the following columns:
    1) A column of sample names (samples with the same name will be pooled)
    2) A column designating whether to include or skip the samplles 
       (include = 'Success/Pass/Include'; skip = 'Fail/Skip')
    3) A column designating the sample labware name
    4) A column designating the sample labware type (eg., '96 Well Eppendorf TwinTec PCR')
    5) A column designating the sample position (well)
        
    Mapping file:
    If a mapping file is provided (same names as in the pooling file),
    then the mapping file will be trimmed to just those pooled, and
    the final pooled locations will be added to the mapping table. 
    The added columns have the prefix: "TECAN_postPool_*"

    Notes:
    * Sample locations in plates numbered are column-wise. 
    * All volumes are in ul.
    """
    if subparsers:
        parser = subparsers.add_parser('pool', description=desc, epilog=epi,
                                       formatter_class=argparse.RawTextHelpFormatter)
    else:
        parser = argparse.ArgumentParser(description=desc, epilog=epi,
                                         formatter_class=argparse.RawTextHelpFormatter)
        
    # args
    ## I/O
    groupIO = parser.add_argument_group('I/O')
    groupIO.add_argument('samplefiles', metavar='SampleFile', type=str, nargs='+',
                         help='An excel or tab-delim file of samples to pool')
    groupIO.add_argument('--prefix', type=str, default='TECAN_pool',
                         help='Output file name prefix (default: %(default)s)')
    groupIO.add_argument('--mapfile', type=str, 
                         help='A QIIME-formatted mapping file')
    
    ## file format
    filef = parser.add_argument_group('Sample file details')
    ### sample file
    filef.add_argument('--sample-format', type=str, default=None,
                        help='File format (excel or tab). If not provided, the format is determined from the file extension') 
    filef.add_argument('--sample-header', action='store_false', default=True,
                        help='Header in the sample file? (default: %(default)s)')
    filef.add_argument('--sample-rows', type=str, default='all',
                      help='Which rows (not including header) of the sample file to use ("all"=all rows; "1-48"=rows 1-48) (default: %(default)s)')
    filef.add_argument('--sample-col', type=str, default='Sample',
                        help='Name of column containing the samples  (default: %(default)s)')
    filef.add_argument('--include-col', type=str, default='Call',
                        help='Name of column designating sample include/skip (default: %(default)s)')
    filef.add_argument('--sample-labware-name', type=str, default='labware_name',
                        help='Name of column designating the sample labware name  (default: %(default)s)')
    filef.add_argument('--sample-labware-type', type=str, default='labware_type',
                        help='Name of column designating the sample labware type (default: %(default)s)')
    filef.add_argument('--position-col', type=str, default='Well',
                        help='Name of column designating sample location in the plate (default: %(default)s)')
    ### mapping file
    filef.add_argument('--map-format', type=str, default=None,
                        help='File format (excel or tab). If not provided, the format is determined from the file extension') 
    filef.add_argument('--map-header', action='store_false', default=True,
                        help='Header in the mapping file? (default: %(default)s)')

    ## pooling
    pooling = parser.add_argument_group('Pooling')
    pooling.add_argument('--volume', type=float, default=30.0,
                         help='Per-sample volume to pool (default: %(default)s)')
    pooling.add_argument('--liq-cls', type=str, default='Water Free Single No-cLLD',
                         help='Liquid class for pooling (default: %(default)s)')
    pooling.add_argument('--new-tips',  action='store_true', default=False,
                        help='Use new tips between sample replicates? (default: %(default)s)')

    ## destination plate
    dest = parser.add_argument_group('Destination labware')
    dest.add_argument('--dest-name', type=str, default='Pooled DNA plate',
                      help='Destination labware name (default: %(default)s)')
    dest.add_argument('--dest-type', type=str, default='96 Well Eppendorf TwinTec PCR',
                      help='Destination labware type (default: %(default)s)')
    dest.add_argument('--dest-start', type=int, default=1,
                      help='Starting position (well) on the destination labware (default: %(default)s)')
    
    # parse & return
    if test_args:
        args = parser.parse_args(test_args)
        return args

    return parser


def main(args=None):
    # Input
    if args is None:
        args = parse_args()
    check_args(args)

    # Import
    ## sample file(s); then joining
    df_samps = []
    for f in args.samplefiles:
        df_samp = sample2df(f,
                            sample_col=args.sample_col,
                            include_col=args.include_col,
                            labware_name_col=args.sample_labware_name,
                            labware_type_col=args.sample_labware_type,
                            position_col=args.position_col,
                            file_format=args.sample_format,
                            row_select=args.sample_rows, 
                            header=args.sample_header)
        df_samps.append(df_samp)
    df_samp = pd.concat(df_samps)
    
    ## mapping file
    df_map = map2df(args.mapfile,                    
                    file_format=args.map_format,
                    header=args.map_header)
    
    # filtering sample file to just pass
    df_samp = df_samp.loc[df_samp[args.include_col].isin(['success', 'pass', 'include'])]

    # adding destination
    df_samp = add_dest(df_samp,
                       dest_labware=args.dest_name,
                       sample_col=args.sample_col,
                       position_col=args.position_col,
                       dest_type=args.dest_type,
                       dest_start=args.dest_start)
    df_samp = check_rack_labels(df_samp)        
    
    # gwl construction
    TipTypes = ['FCA, 1000ul SBS', 'FCA, 200ul SBS',
                'FCA, 50ul SBS', 'FCA, 10ul SBS']     
    gwl = Fluent.gwl(TipTypes)
    
    # Reordering dest if plate type is 384-well
    gwl.db.get_labware(args.dest_type)
    n_wells = gwl.db.get_labware_wells(args.dest_type)
    if n_wells == '384':
        df_samp = reorder_384well(df_samp, args.position_col)

    # samples
    pool_samples(df_samp,
                 gwl,
                 sample_col=args.sample_col,
                 labware_name_col=args.sample_labware_name,
                 labware_type_col=args.sample_labware_type,
                 position_col=args.position_col,                     
                 dest_labware_name=args.dest_name,
                 dest_labware_type=args.dest_type,
                 volume=args.volume,
                 liq_cls=args.liq_cls,
                 new_tips=args.new_tips)
    
    ## writing out worklist (gwl) file
    gwl_file = args.prefix + '.gwl'
    gwl.write(gwl_file)

    # making labware table
    lw = Labware.labware()
    lw.add_gwl(gwl)
    lw_df = lw.table()
    lw_file = args.prefix + '_labware.txt'
    lw_df.to_csv(lw_file, sep='\t', index=False)

    # Writing out updated mapping table
    if df_map is not None:
        df_map = filter_map(df_map, df_samp, args.sample_col)
        map_file = args.prefix + '_map.txt'        
        df_map.round(1).to_csv(map_file, sep='\t', index=False)

    # # status
    Utils.file_written(gwl_file)
    Utils.file_written(lw_file)
    if df_map is not None:
        Utils.file_written(map_file)
        
    # end
    if df_map is not None:
        return (gwl_file, lw_file, map_file)
    else:
        return (gwl_file, lw_file) 
    
def check_args(args):
    """Checking user input
    """
    # input table column IDs
    args.rows = Utils.make_range(args.sample_rows, set_zero_index=True)
    # dilution
    assert args.volume >= 0.0, '--volume must be >= 0'
                         
def sample2df(samplefile, sample_col, include_col,
              labware_name_col, labware_type_col, position_col,
              row_select=None, file_format=None, header=True):
    """Loading a sample file as a pandas dataframe
    """
    if header==True:
        header=0
    else:
        header=None
    # format
    if file_format is None:
        if samplefile.endswith('.csv'):
            file_format = 'csv'
        elif samplefile.endswith('.txt'):
            file_format = 'tab'
        elif samplefile.endswith('.xls') or samplefile.endswith('.xlsx'):
            file_format = 'excel'
    else:
        file_format = file_format.lower()
        
    # load via pandas IO
    if file_format == 'csv':
        df = pd.read_csv(samplefile, sep=',', header=header)        
    elif file_format == 'tab':
        df = pd.read_csv(samplefile, sep='\t', header=header)
    elif file_format == 'excel':
        xls = pd.ExcelFile(samplefile)
        df = pd.read_excel(xls, header=header)
    else:
        raise ValueError('Sample file is not in a usable format')

    # checking dataframe format
    ## columns
    req_cols = [sample_col, include_col, labware_name_col, labware_type_col, position_col]
    msg = 'Column "{}" not found in sample table'
    for req_col in req_cols:
        if req_col not in df.columns.values:
            raise ValueError(msg.format(req_col))    
    ## include col
    f = lambda x: x.lower()
    df.loc[:,include_col] = df.loc[:,include_col].apply(f)
    msg = '"{}" value not allowed in include column in sample file'
    df.loc[:,include_col].apply(check_include_column)
    ## converting wells to positions
    lw_utils = Labware.utils()
    f = lambda row: lw_utils.well2position(row[position_col],
                                           RackType=row[labware_type_col])
    df[position_col] = df.apply(f, axis=1)
        
    # selecting relevant columns
    df = df.loc[:,req_cols]
    # ordering by position
    df = df.sort_values(position_col)
    
    # return
    return df

def check_include_column(x):
    psbl_vals = ('success', 'include', 'pass', 'fail', 'skip')
    assert x in psbl_vals, msg.format(x)

def check_rack_labels(df_samp):
    """Removing '.' for rack labels (causes execution failures)
    """
    cols = ['labware_name', 'TECAN_dest_labware_name']
    for x in cols:
        df_samp[x] = [y.replace('.', '_') for y in df_samp[x].tolist()]
    return df_samp
    
def map2df(mapfile, file_format=None, header=True):
    """Loading a mapping file as a pandas dataframe
    """
    if mapfile is None:
        return None
    if header==True:
        header=0
    else:
        header=None
    # format
    if file_format is None:
        if mapfile.endswith('.csv'):
            file_format = 'csv'
        elif mapfile.endswith('.txt'):
            file_format = 'tab'
        elif mapfile.endswith('.xls') or mapfile.endswith('xlsx'):
            file_format = 'excel'
    else:
        file_format = file_format.lower()
        
    # load via pandas IO
    if file_format == 'csv':
        df = pd.read_csv(mapfile, sep=',', header=header)        
    elif file_format == 'tab':
        df = pd.read_csv(mapfile, sep='\t', header=header)
    elif file_format == 'excel':
        xls = pd.ExcelFile(mapfile)
        df = pd.read_excel(xls, header=header)
    else:
        raise ValueError('Mapping file is not in a usable format')
    
    # checking for required columns
    req_cols = ['#SampleID']
    msg = 'Column "{}" not found in mapping file'
    for req_col in req_cols:
        if req_col not in df.columns.values:
            raise ValueError(msg.format(req_col))    
    
    # ret
    return df

    
def add_dest(df, dest_labware, sample_col, position_col,
             dest_type='96 Well Eppendorf TwinTec PCR',
             dest_start=1):
    """Setting destination locations for samples & primers.
    Making a new dataframe with:
      [sample, sample_rep, dest_labware, dest_location]
    * For each sample (i):
      * For each replicate (ii):
        * plate = destination plate type
        * well = i * (ii+1) + (ii+1) + start_offset
    Joining to df
    """
    dest_start= int(dest_start)
    lw_utils = Labware.utils()
    # labware type found in DB?
    positions = lw_utils.get_wells(dest_type)
    if positions is None:
        msg = 'RackType has no "wells" value: "{}"'
        raise ValueError(msg.format(dest_type))

    # init destination df
    cols = ['TECAN_dest_labware_name',
            'TECAN_dest_labware_type', 
            'TECAN_dest_target_position']    
    df_dest = pd.DataFrame(np.nan, index=range(df.shape[0]), columns=cols)

    # number of destination plates required
    n_dest_plates = round(df_dest.shape[0] / positions + 0.5, 0)
    if n_dest_plates > 1:
        msg = ('WARNING: Not enough wells for the number of samples.' 
        ' Using multiple destination plates')
        print(msg, file=sys.stderr)
        
    # filling destination df
    ## for position, just 1 position per sample
    samples = {}
    for i,sample in enumerate(df.loc[:,sample_col]):
        # dest position
        try:
            dest_position = samples[sample]
        except KeyError:
            dest_position = len(samples.keys()) + 1
            samples[sample] = dest_position                                
        # dest location
        dest_position = positions if dest_position % positions == 0 else dest_position % positions 
        # destination plate name
        if n_dest_plates > 1:
            x = round((i + dest_start) / positions + 0.499, 0)        
            dest_labware = '{} {}'.format(orig_dest_labware, int(x))
        # adding values DF; sample left off
        df_dest.iloc[i] = [dest_labware, dest_type, dest_position]

    # df join (map + destination)
    df.index = df_dest.index
    df_j = pd.concat([df, df_dest], axis=1)
    
    # return
    return df_j


def pool_samples(df, gwl, sample_col, labware_name_col,
                 labware_type_col, position_col,
                 dest_labware_name, dest_labware_type,
                 volume, liq_cls='Water Free Single No-cLLD',
                 new_tips=False, lw_tracker=None):
    """Writing gwl commands for pooling sample replicates
    """
    gwl.add(Fluent.Comment('Sample pooling'))

    # sorting by postion
    df = df.sort_values('TECAN_dest_target_position')
    
    # for each Sample, generate asp/dispense commands
    ## optional: keep tips among sample replicates
    for sample in df[sample_col].unique():
        df_sub = df.loc[df[sample_col] == sample]
        df_sub.index = range(df_sub.shape[0])
        for i in range(df_sub.shape[0]):
            # aspiration
            asp = Fluent.Aspirate()
            asp.RackLabel = df_sub.loc[i, labware_name_col]
            asp.RackType = df_sub.loc[i, labware_type_col]
            asp.Position = df_sub.loc[i, position_col]
            asp.Volume = volume 
            asp.LiquidClass = liq_cls
            gwl.add(asp)

            # dispensing
            disp = Fluent.Dispense()
            disp.RackLabel = df_sub.loc[i,'TECAN_dest_labware_name']
            disp.RackType = df_sub.loc[i,'TECAN_dest_labware_type']
            disp.Position = df_sub.loc[i,'TECAN_dest_target_position']
            disp.Volume = volume
            disp.LiquidClass = liq_cls
            gwl.add(disp)

            # tip to waste (each replicate)
            if new_tips == True:
                gwl.add(Fluent.Waste())
            else:
                gwl.add(Fluent.Flush())
                
        # tip to waste (between samples)
        if new_tips == False:            
            gwl.add(Fluent.Waste())


def filter_map(df_map, df_samp, sample_col):
    """Filtering df_sample to just destination position, 
    then adding values to df_map
    """
    # formatting sample table
    cols = [sample_col, 'TECAN_dest_labware_name',
            'TECAN_dest_labware_type', 'TECAN_dest_target_position']
    df_samp = df_samp[cols].drop_duplicates()
    x = 'TECAN_dest_target_position'
    df_samp[x] = df_samp[x].astype(int)
    df_samp.columns = [sample_col,
                       'TECAN_postPool_labware_name',
                       'TECAN_postPool_labware_type',
                       'TECAN_postPool_target_position']
    # formatting mapping table
    df_map = df_map.drop_duplicates(subset='#SampleID')
    # joining 
    df_map = pd.merge(df_map, df_samp, how='inner',
                      left_on=['#SampleID'], right_on=[sample_col])
    return df_map

            
# main
if __name__ == '__main__':
    pass


