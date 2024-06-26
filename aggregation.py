import blechpy
import os
import numpy as np
import pandas as pd
from tqdm import tqdm
from sklearn.decomposition import PCA
from scipy.ndimage.filters import gaussian_filter1d
from scipy.stats import sem
from blechpy import project, experiment, dataset, load_dataset, load_experiment
from blechpy.analysis import held_unit_analysis as hua
from blechpy.analysis import spike_analysis as sas
from blechpy.dio import h5io
from blechpy.utils import print_tools as pt
from collections.abc import Mapping


PAL_MAP = {'Spont': -1, 'Suc': 1, 'QHCl': 4,
           'CA': 3, 'NaCl': 2}

ELECTRODES_IN_GC = {'DS31':'both','DS33':'both','DS36':'both','DS39':'both','DS40':'both', 'DS41':'both', 'DS41':'both', 'DS42':'both','DS44':'both','DS45':'both','DS46':'both','DS47':'both'}


# E1 = ['DS33_spont_taste_200305_153504',
#          'DS36_spont_taste_200924_145722',
#          'DS39_spont_taste_201029_154308',
#          'DS40_spont_taste_201103_150101',
#          'DS46_spont_taste_210715_104121',
#          'DS47_spont_taste_210815_123224',
#          'DS45_spont_taste_210815_104650',
#          'DS41_spont_taste_210702_164709']

# NV = ['DS33_spont_taste_200305_153504',
#          'DS36_spont_taste_200924_145722',
#          'DS39_spont_taste_201029_154308',
#          'DS40_spont_taste_201103_150101',
#          'DS46_spont_taste_210715_104121']
         
# PE = ['DS47_spont_taste_210815_123224',
#       'DS45_spont_taste_210815_104650',
#       'DS41_spont_taste_210702_164709']

# REC GROUP IS DAY
# EXP GROUP IS EXPERIMENTAL GROUP
# CTA GROIP IS IF THEY LEARNED CTA
def get_all_units(proj):
    # Columns:
    #   - exp_name, exp_group, rec_name, rec_group, rec_dir, unit_num,
    #   - electrode, area, single, unit_type
    all_units = pd.DataFrame(columns=['exp_name', 'rec_name', 'exp_group', 'rec_num',
                                      'rec_group','time_group', 'rec_dir', 'unit_name',
                                      'unit_num', 'electrode', 'area',
                                      'single_unit', 'regular_spiking',
                                      'fast_spiking','spike_start','spike_end'])
    for i, row in proj.rec_info.iterrows():
        rec_dir = row['rec_dir']
        dat = load_dataset(rec_dir)
        snapshot = dat.clustering_params.get('spike_snapshot')
        spike_start = snapshot.get('Time before spike (ms)')
        spike_end = snapshot.get('Time after spike (ms)')
        units = dat.get_unit_table().copy()
        
        units['exp_name'] = row['exp_name']
        units['rec_name'] = row['rec_name']
        units['exp_group'] = row['exp_group']
        units['rec_num'] = row['rec_num']
        units['time_group'] = str(row['rec_num'])
        units['rec_group'] = row['rec_group']
        units['rec_dir'] = row['rec_dir']
        units['spike_start'] = spike_start
        units['spike_end'] = spike_end

        em = dat.electrode_mapping.copy().set_index('Electrode')
        units['area'] = units['electrode'].map(em['area'])
        units = units[all_units.columns]
        all_units = all_units.append(units).reset_index(drop=True)
        all_units = all_units.drop_duplicates()

    return all_units

def find_held_units(proj, percent_criterion=95, raw_waves=False):
    all_units = get_all_units(proj)
    sing_units = all_units[all_units['single_unit']==True]
    sing_units['intra_J3'] = sing_units.apply(lambda x: get_unit_J3(x['rec_dir'],
                                                                    x['unit_name'],
                                                                    raw_waves=raw_waves),
                                              axis=1)
    all_units.loc[sing_units.index, 'intra_J3'] = sing_units['intra_J3']
    threshold = np.percentile(sing_units['intra_J3'], percent_criterion)
    rec_dirs = sing_units['rec_dir'].unique().tolist()

    # Loop through animal, electrode, rec pairs
    # Store rec1, el1, unit1, rec2, el2, unit2, interJ3, held, held_unit_name
    held_df = pd.DataFrame(columns=['rec1', 'unit1', 'rec2', 'unit2',
                                    'inter_J3', 'held', 'held_unit_name', 'exp_group', 'rec_num','time_group', 'exp_name'])
    for group_name, group in sing_units.groupby(['exp_name', 'electrode']):
        anim = group_name[0]
        electrode = group_name[1]
        
        rec_order = sorted(group.rec_num.unique())
        for i, row in group.iterrows():
            rec_group = row['rec_group']
            rec1 = row['rec_dir']
            rec_name1 = row['rec_name']
            unit1 = row['unit_name']
            #reg_spike = row['regular_spiking']
            #fast_spike = row['fast_spiking']
            rec_num = row['rec_num']
            time_group = row['time_group']
            
            idx = rec_order.index(rec_num)
            
            if idx == len(rec_order)-1:
                continue

            next_group = rec_order[idx+1]
            g2 = group.query('rec_num == @next_group')# and '
                             #'regular_spiking == @reg_spike and '
                             #'fast_spiking == @fast_spike')
            if g2.empty:
                continue

            for j, row2 in g2.iterrows():
                rec2 = row2['rec_dir']
                unit2 = row2['unit_name']
                rec_name2 = row2['rec_name']
                print('Comparing %s %s vs %s %s' % (rec_name1, unit1,
                                                    rec_name2, unit2))
                J3 = get_inter_J3(rec1, unit1, rec2, unit2, raw_waves=raw_waves)
                held_df = held_df.append({'rec1': rec1, 'unit1': unit1,
                                          'rec2': rec2, 'unit2': unit2,
                                          'inter_J3': J3, 'exp_group': row['exp_group'],
                                          'exp_name': anim},
                                         ignore_index=True)

    new_held_df = None
    for group_name, group in held_df.groupby('exp_group'):
        thresh = np.percentile(sing_units.query('exp_group == @group_name')['intra_J3'],
                               percent_criterion)
        tmp = resolve_matches(group, thresh)
        if new_held_df is None:
            new_held_df = tmp
        else:
            max_num = new_held_df['held_unit_name'].max()
            tmp['held_unit_name'] = tmp['held_unit_name'] + max_num
            new_held_df = new_held_df.append(tmp, ignore_index=True).reset_index(drop=True)

    #held_df = resolve_matches(held_df, threshold)
    if new_held_df is not None:
        held_df = new_held_df.copy()

    # Now put the unit letters into the all_units array
    for i, row in held_df.iterrows():
        if not row['held']:
            continue

        r1 = row['rec1']
        u1 = row['unit1']
        r2 = row['rec2']
        u2 = row['unit2']
        letter = row['held_unit_name']
        tmp = all_units.query('(rec_dir == @r1 and unit_name == @u1) or '
                              '(rec_dir == @r2 and unit_name == @u2)')
        if tmp.empty:
            raise ValueError('Units not found')

        all_units.loc[tmp.index, 'held_unit_name'] = letter

    return all_units, held_df
    # Plot J3 distributions
    # Save dataframes

def get_inter_J3(rec1, unit1, rec2, unit2, raw_waves=False):
    if raw_waves:
        wf1, descrip1, fs1 = h5io.get_raw_unit_waveforms(rec1, unit1)
        wf2, descrip2, fs2 = h5io.get_raw_unit_waveforms(rec2, unit2)
    else:
        wf1, descrip1, fs1 = h5io.get_unit_waveforms(rec1, unit1)
        wf2, descrip2, fs2 = h5io.get_unit_waveforms(rec2, unit2)
    
    if wf1.shape[1] != wf2.shape[1]:
        print('warning: different length spike snapshots, trimming to match. Consider re-clustering & sorting with equal snapshot lengths')
        diff = wf1.shape[1]-wf2.shape[1]
        
        if diff > 0:
            wf1 = wf1[:,diff:]
        else:
            wf2 = wf2[:,-diff:] 
            
    if fs1 > fs2:
        wf1 = sas.interpolate_waves(wf1, fs1, fs2)
    elif fs1 < fs2:
        wf2 = sas.interpolate_waves(wf2, fs2, fs1)

    pca = PCA(n_components=3)
    pca.fit(np.concatenate((wf1, wf2), axis=0))
    pca_wf1 = pca.transform(wf1)
    pca_wf2 = pca.transform(wf2)

    J3 = hua.calc_J3(pca_wf1, pca_wf2)
    return J3

def _get_inter_J3(rec1, unit1, rec2, unit2, raw_waves=False):
    if raw_waves:
        wf1, descrip1, fs1 = h5io.get_raw_unit_waveforms(rec1, unit1)
        wf2, descrip2, fs2 = h5io.get_raw_unit_waveforms(rec2, unit2)
    else:
        wf1, descrip1, fs1 = h5io.get_unit_waveforms(rec1, unit1)
        wf2, descrip2, fs2 = h5io.get_unit_waveforms(rec2, unit2)
        

    if fs1 > fs2:
        wf1 = sas.interpolate_waves(wf1, fs1, fs2)
    elif fs1 < fs2:
        wf2 = sas.interpolate_waves(wf2, fs2, fs1)

    pca = PCA(n_components=3)
    pca.fit(np.concatenate((wf1, wf2), axis=0))
    pca_wf1 = pca.transform(wf1)
    pca_wf2 = pca.transform(wf2)

    J3 = hua.calc_J3(pca_wf1, pca_wf2)
    return J3


def get_unit_J3(rec_dir, unit, raw_waves=False):
    print('Getting intra-recording J3 for %s :: %s' % (rec_dir, unit))
    if raw_waves:
        waves, descrip, fs = h5io.get_raw_unit_waveforms(rec_dir, unit)
    else:
        waves, descrip, fs = h5io.get_unit_waveforms(rec_dir, unit)

    pca = PCA(n_components=3)
    pca.fit(waves)
    pca_waves = pca.transform(waves)
    idx1 = int(waves.shape[0] * (1.0 / 3.0))
    idx2 = int(waves.shape[0] * (2.0 / 3.0))

    J3 = hua.calc_J3(pca_waves[:idx1, :], pca_waves[idx2:, :])
    return J3


def resolve_matches(df, thresh):
    df = df.copy()
    df['held'] = False
    df['done'] = False
    df.loc[df['inter_J3'] >= thresh, 'done'] = True
    while any(df['done'] == False):
        for name, group in df.groupby(['rec1', 'rec2']):
            tmp = group[group['inter_J3'] < thresh].copy()
            tmp = tmp[tmp['done'] == False]
            if tmp.empty:
                continue

            for u1 in tmp.unit1.unique():
                all_idx = tmp.index[tmp.unit1 == u1]
                a = np.argmin(np.array(tmp.loc[all_idx,'inter_J3']))
                idx = tmp.loc[all_idx, 'inter_J3'].idxmin()
                u2 = tmp.loc[idx, 'unit2']
                u2_idx = tmp.index[tmp.unit2 == u2]
                bidx = tmp.loc[u2_idx, 'inter_J3'].idxmin()
                if idx == bidx:
                    others = all_idx.union(u2_idx)
                    others = others.drop(idx)
                    df.loc[idx, 'held'] = True
                    df.loc[others, 'held'] = False
                    df.loc[idx, 'done'] = True
                    df.loc[others, 'done'] = True

    unit_num = 0
    tmp = df[df.held].copy()
    for i, row in tmp.iterrows():
        r1 = row['rec1']
        u1 = row['unit1']
        tmp2 = tmp.query('rec2 == @r1 and unit2 == @u1')
        if tmp2.empty:
            df.loc[i, 'held_unit_name'] = unit_num
            unit_num += 1
        elif len(tmp2) == 1:
            i2 = tmp2.index[0]
            un = df.loc[i2, 'held_unit_name']
            if pd.isnull(un):
                un = unit_num
                unit_num += 1
                df.loc[i2, 'held_unit_name'] = un

            df.loc[i, 'held_unit_name'] = un
        else:
            raise ValueError('Too many matches')

    df = df.drop(columns=['done'])
    return df


def get_firing_rate_trace(rec, unit, ch, bin_size, step_size=None, t_start=None,
                          t_end=None, baseline_win=None, remove_baseline=False):
    '''Gets the spike array for a unit and returns the binned firing rate. If
    t_start and/or t_end are given then the data will be cut accordingly. If
    remove_baseline is true then the baseline firing rate will be
    averaged and subtracted from the firing rate traces.
    If step_size is not given then step_size = bin_size
    All time units in ms.

    Returns
    -------
    time: np.array, time vector in ms, corresponds to bin centers
    firing_rate: np.array
    baseline: tuple
        (mean, sem) of baseline firing rate, if baseline_win is not provided
        then this is computed using all time<0
    '''
    if step_size is None:
        step_size = bin_size

    t, sa = h5io.get_spike_data(rec, unit, ch)

    if baseline_win is None:
        baseline_win = np.min(t)
        baseline_win = np.min((baseline_win, 0)) # in case t doesn't have values less than 0
        baseline_win = np.abs(baseline_win)

    if baseline_win == 0:
        baseline = 0
        baseline_sem = 0
    else:
        idx = np.where((t < 0) & (t >= -baseline_win))[0]
        tmp = np.sum(sa[:, idx], axis=1) / (baseline_win / 1000)
        baseline = np.mean(tmp)
        baseline_sem = sem(tmp)
        del idx, tmp

    # trim arrays
    if t_start is not None:
        idx = np.where((t >= t_start))[0]
        t = t[idx]
        sa = sa[:, idx]
        del idx

    if t_end is not None:
        idx = np.where((t <= t_end))[0]
        t = t[idx]
        sa = sa[:, idx]
        del idx

    bin_time, FR = sas.get_binned_firing_rate(t, sa, bin_size, step_size)
    if remove_baseline:
        FR = FR - baseline

    return bin_time, FR, (baseline, baseline_sem)


def get_psth(rec, unit, ch, params, remove_baseline=False):
    baseline_win = params['baseline_comparison']['win_size']
    psth_bin = params['psth']['win_size']
    psth_step = params['psth']['step_size']
    smoothing = params['psth']['smoothing_win']
    psth_start = params['psth']['plot_window'][0]
    psth_end = params['psth']['plot_window'][1]
    pt, psth, baseline = get_firing_rate_trace(rec, unit, ch,
                                               bin_size=psth_bin,
                                               step_size=psth_step,
                                               t_start=psth_start,
                                               t_end=psth_end,
                                               baseline_win=baseline_win,
                                               remove_baseline=remove_baseline)

    return pt, psth, baseline


def fix_palatability(proj, pal_map=None):
    '''Goes through all datasets in project and fixes palatability rankings
    '''
    if pal_map is None:
        pal_map = PAL_MAP

    exp_dirs = proj._exp_info.exp_dir.to_list()

    for exp_dir in tqdm(exp_dirs):
        exp = blechpy.load_experiment(exp_dir)
        for rd in exp.recording_dirs:
            dat = load_dataset(rd)
            dat.dig_in_mapping['palatability_rank'] = dat.dig_in_mapping.name.map(pal_map)
            h5io.write_digital_map_to_h5(dat.h5_file, dat.dig_in_mapping, 'in')
            dat.save()


def set_electrode_areas(proj, el_in_gc={}):
    exp_info = proj._exp_info
    for i, row in exp_info.iterrows():
        name = row['exp_name']
        if name not in el_in_gc.keys():
            continue

        exp = blechpy.load_experiment(row['exp_dir'])
        ingc = el_in_gc[name]
        if ingc is 'right':
            el = np.arange(8, 24)
        elif ingc is 'left':
            el = np.concatenate([np.arange(0,8), np.arange(24, 32)])
        elif ingc is 'none':
            el = np.arange(0,32)
        else:
            el = None

        for rec in exp.recording_dirs:
            dat = load_dataset(rec)
            print('Fixing %s...' % dat.data_name)
            em = dat.electrode_mapping
            em['area'] = 'GC'
            if el is not None:
                em.loc[em['Channel'].isin(el), 'area'] = 'STR'

            h5io.write_electrode_map_to_h5(dat.h5_file, em)
            dat.save()

    return


def get_valid_trials(state_seqs, states, min_pts=1, time=None):
    '''returns the indices of all trials where all of the given states are present and
    have more than min_pts consecutive points in each state. If time is given,
    this will only return trials in which the state is present after t=0
    '''
    #commented out requirement that state be present after t=0 since I am now analyzing baseline activity
    #if time is not None and 0 not in states:
        #tidx = np.where(time > 0)[0]
        #state_seqs = state_seqs.copy()[:, tidx]

    out = []
    for i, row in enumerate(state_seqs):
        if any([x not in row for x in states]):
            continue
        
        if len(np.unique(row)) == 1: #remove single-state trials
            continue
        
        good = True
        summary = summarize_sequence(row)
        for state in states:
            idx = np.where(summary[:,0] == state)[0]
            if not any(summary[idx,-1] >= min_pts):
                good = False

        if good:
            out.append(i)

    return np.array(out)


def summarize_sequence(path):
    '''takes a 1-D sequences of categorical info and returns a matrix with
    columns: state, start_idx, end_idx, duration in samples
    '''
    tmp_path = path.copy()
    out = []
    a = np.where(np.diff(path) != 0)[0]
    starts = np.insert(a+1,0,0)
    ends = np.insert(a, len(a), len(path)-1)
    for st, en in zip(starts, ends):
        out.append((path[st], st, en, en-st+1))

    return np.array(out)

def write_dict_to_txt(dat, save_file=None, tabs=0):
    out = []
    for k,v in dat.items():
        out.append('\t'*tabs + str(k))
        if isinstance(v, Mapping):
            out.extend(write_dict_to_txt(v, tabs=tabs+1))
        elif isinstance(v, pd.DataFrame):
            if isinstance(v.index, pd.core.indexes.range.RangeIndex):
                index=False
            else:
                index=True

            tmp = v.to_string(index=index)
            tmp = '\t'*tabs + tmp.replace('\n', '\n'+'\t'*tabs)
            out.append(tmp)
            out.append('')
        else:
            out[-1] = out[-1] + ': ' + str(v)

    if save_file:
        with open(save_file, 'w') as f:
            f.write('\n'.join(out))
    else:
        return out


def apply_grouping_cols(df, proj):
    if 'exclude' not in proj._exp_info.columns:
        proj._exp_info['exclude'] = proj._exp_info.apply(apply_exclude, axis=1)
        proj.save()
    base_cols = ['exp_name', 'exp_dir', 'rec_dir']
    cols = list(df.columns)
    if not any([x in cols for x in base_cols]):
        return df

    if 'exp_name' not in cols:
        if 'exp_dir' in cols:
            def exp_name(ed):
                exp = load_experiment(ed)
                return exp.data_name
            from_col = 'exp_dir'
        elif 'rec_dir' in cols:
            def exp_name(rd):
                dat = load_dataset(rd)
                en = dat.data_name.split('_')[0]
                if en == 'RN5b':
                    en = 'RN5'
                return en
            from_col = 'rec_dir'

        df['exp_name'] = df[from_col].apply(exp_name)

    map_df = proj._exp_info.set_index('exp_name')
    #df['cta_group'] = df['exp_name'].map(map_df['cta_group'].to_dict())
    df['exp_group'] = df['exp_name'].map(map_df['exp_group'].to_dict())
    df['exclude'] = df.apply(apply_exclude, axis=1)

        
    # if 'rec_group' in df.columns:
    #     col = 'rec_group'
    if 'rec_dir' in df.columns:
        col = 'rec_dir'
    else:
        return df

    # def time_group(x):
    #     x = os.path.basename(x)
    #     if 'pre' in x or 'Train' in x:
    #         return 'preCTA'
    #     elif 'post' in x or 'Test' in x:
    #         return 'postCTA'
    #     elif x in E1:
    #         return 'Exposure_1'
    #     elif x in E2:
    #         return 'Exposure_2'
    #     elif x in E3:
    #         return 'Exposure_3'
    #     else:
    #         return None

    # df['time_group'] = df[col].apply(time_group)
    return df


def apply_exclude(row):
    '''exclude GFP - No CTA and Cre - CTA'''
    if (row['exp_group'] == 'GFP' and row['cta_group'] == 'No CTA'):
        return True

    if (row['exp_group'] == 'Cre' and row['cta_group'] == 'CTA'):
        return True
    if ('taste' in row):
        if (row['taste'] == 'Spont'):
            return True

    return False
