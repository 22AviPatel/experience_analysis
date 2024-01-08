
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Mar  7 12:32:58 2021

@author: dsvedberg, avi patel
"""

import timeit
import os
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
#get into the directory
import analysis as ana
import blechpy
#import new_plotting as nplt
#import hmm_analysis as hmma 
from blechpy import dio
import seaborn as sns
import hmm_analysis as hmma
from multiprocessing import Pool
from scipy.stats import zscore
import trialwise_analysis as ta

#you need to make a project analysis using blechpy.project() first
proj_dir =  '/media/dsvedberg/Ubuntu Disk/taste_experience_resorts_copy'
proj = blechpy.load_project(proj_dir)
proj.make_rec_info_table() #run this in case you changed around project stuff

PA = ana.ProjectAnalysis(proj)

def get_held_resp(PA):
    PA.detect_held_units(overwrite = False) #this part also gets the all units file
    [all_units, held_df] = PA.get_unit_info(overwrite=False) #run and check for correct area then run get best hmm

    #check df for nan in HMMID or early or late state
    held_df = held_df[held_df.held !=False]
    held_df.reset_index(drop=True, inplace=True)
    id_vars = ['held_unit_name', 'exp_group', 'exp_name', 'held', 'area']
    filter_cols = id_vars + ["rec1", "rec2", "unit1", "unit2"]
    held_df = held_df[filter_cols]
    held_df_long = pd.melt(held_df, id_vars=id_vars, value_vars=['rec1', 'rec2'], value_name='rec_dir', var_name='rec_order')
    held_df_long2 = pd.melt(held_df, id_vars=id_vars, value_vars=['unit1', 'unit2'], value_name='unit_num', var_name='unit_order')
    # drop the unit_order columns
    held_df_long = held_df_long.drop(['rec_order'], axis=1)
    held_df_long2 = held_df_long2.drop(['unit_order'], axis=1)

    held_df_long = pd.concat([held_df_long, held_df_long2], axis=1)

    final_cols = ['held_unit_name', 'exp_group', 'exp_name', 'held', 'rec_dir', 'unit_num']
    held_df_long = held_df_long[final_cols]
    #remove the  duplicated columns
    held_df_long = held_df_long.T.drop_duplicates().T
    held_df_long = held_df_long.drop_duplicates()
    held_df_long['unit_name'] = held_df_long['unit_num']

    resp_units, pal_units = PA.process_single_units(overwrite=False) #run the single-unit analysis, check function to see if all parts are working
    respidxs = resp_units[['rec_dir', 'unit_name', 'taste', 'taste_responsive']].drop_duplicates()
    #get rows from held_df_long where [rec_dir, unit_name] is in respidxs
    held_resp = held_df_long.merge(respidxs, on=['rec_dir', 'unit_name']).drop_duplicates()
    #group by held_unit_name and remove all groups where no row of the group has held == True
    for name, group in held_resp.groupby(['held_unit_name']):
        if not any(group[['taste_responsive', 'taste']]):
            held_resp = held_resp[held_resp.held_unit_name != name]

    return held_resp

#%% pull spike arrays or rate arrays for units matching any arbitrary list of units
def get_arrays(name, group, query_name='spike_array', query_func = dio.h5io.get_spike_data):
    #get spike arrays or rate arrays (or whatever) for each unit in each recording
    #use the query_func to get the arrays
    #query_name
    # Initialize lists for this group
    sessiontrials = []
    tastetrials = []
    queried_arr = []
    timedata = []
    rec_dir = []
    held_unit_name = []
    interj3 = []
    digins = []
    unit_nums = []

    dat = blechpy.load_dataset(name)
    dinmap = dat.dig_in_mapping.query('spike_array ==True')
    tastemap = dinmap[['channel', 'name']]
    #rename column 'name' to 'taste'
    tastemap = tastemap.rename(columns={'name': 'taste'})
    group = group.merge(tastemap, on=['taste'])
    unittable = dat.get_unit_table()
    digintrials = dat.dig_in_trials
    digintrials['tasteExposure'] = digintrials.groupby(['name', 'channel']).cumcount()+1
    digintrials = digintrials.loc[digintrials.name != 'Experiment'].reset_index(drop=True)

    for i , row in group.iterrows():
        print(i)
        unum = unittable.loc[unittable.unit_name == row.unit_num]
        unum = unum.unit_num.item()

        trials = digintrials.loc[digintrials.channel == row['channel']]
        time, arrays = query_func(row.rec_dir, unum, row['channel'])
        for k, array in enumerate(arrays):
            sessiontrials.append(trials.trial_num.iloc[k])
            tastetrials.append(trials.tasteExposure.iloc[k])
            queried_arr.append(array)
            timedata.append(time)
            rec_dir.append(name)
            held_unit_name.append(row.held_unit_name)
            unit_nums.append(group['unit_num'][i])
            digins.append(row.channel)
    # Construct a list of dictionaries for this group
    data_dicts = [{
        query_name: qa,
        'time_array': td,
        'session_trial': ss,
        'taste_trial': tt,
        'rec_dir': rd,
        'held_unit_name': hun,
        'din': di,
        'unit_num': un
    } for qa, td, ss, tt, rd, hun, di, un in zip(queried_arr, timedata, sessiontrials, tastetrials, rec_dir, held_unit_name, digins, unit_nums)]
    return data_dicts

def get_rate_arrays(name, group):
    return get_arrays(name, group, query_name='rate_array', query_func=dio.h5io.get_rate_data)

# Split the data into chunks for parallel processing
def get_rate_array_df(PA):
    held_resp = get_held_resp(PA)
    groups = list(held_resp.groupby(['rec_dir']))
    # Use multiprocessing to process each group in parallel
    with Pool(processes=4) as pool:  # Adjust the number of processes based on your CPU cores
        results = pool.starmap(get_rate_arrays, groups)

    results

    # Flatten the results and construct the DataFrame
    all_data = [item for sublist in results for item in sublist]
    df = pd.DataFrame(all_data)

    proj = PA.project
    rec_info = proj.get_rec_info()
    ri_formerge = rec_info[['exp_name', 'exp_group', 'rec_num', 'rec_dir']]
    # rename rec_num to session
    ri_formerge = ri_formerge.rename(columns={'rec_num': 'session'})

    # apply columns from ri_formerge to df along rec_dir column
    df = df.merge(ri_formerge, on=['rec_dir'])
    df = df.loc[df.din < 4].reset_index(drop=True)

    # make column with miniumum session trial
    df['min_session_trial'] = df.groupby(['rec_dir'])['session_trial'].transform(min)
    df['session_trial'] = df['session_trial'] - df['min_session_trial']

    return df

rate_array_df = get_rate_array_df(PA)
taste_map = {0: 'Suc', 1: 'NaCl', 2: 'CA', 3: 'QHCl', 4: 'Spont'}
rate_array_df['taste'] = rate_array_df['din'].map(taste_map)
cols = ['rec_dir', 'held_unit_name', 'unit_num', 'session_trial', 'taste']
rate_array_df = rate_array_df.drop_duplicates(subset=cols)

zscore_df_list = []
for name, group in rate_array_df.groupby(['exp_name', 'held_unit_name']):
    dflist = []
    for i, row in group.iterrows():
        rates = row.rate_array
        time = row.time_array
        df = pd.DataFrame({'rate': rates, 'time': time})
        df['rec_dir'] = row.rec_dir
        df['held_unit_name'] = row.held_unit_name
        df['unit_num'] = row.unit_num
        df['session_trial'] = row.session_trial
        df['taste'] = row.taste
        dflist.append(df)
    df = pd.concat(dflist)
    #make column 'zscore' the z-score across the entire 'rate' column
    df['zscore'] = zscore(df['rate'])

    zscore_list = []
    nmlist = []
    #make a dataframe where each column is an entry of nm
    for nm, gr in df.groupby(cols):
        zscore_list.append(gr['zscore'].to_numpy())
        nmlist.append(nm)
    zscore_df = pd.DataFrame(nmlist, columns=cols)
    zscore_df['zscore'] = zscore_list
    zscore_df_list.append(zscore_df)
zscore_df = pd.concat(zscore_df_list)
#merge zscore_df into rate_array_df along cols
rate_array_df = rate_array_df.merge(zscore_df, on=cols) #TODO: figure out why this makes rate array shorter

#modfiy rate_array_df to have columns for prestim, early, late, end, their magntitudes, their maxes and tmaxes, and the maxes/tmaxes of the magnitudes
prestim = []
early = []
late = []
end = []
max = []
tmax = []
#prestim_max = []
#early_max = []
#late_max = []
#end_max = []
#prestim_tmax = []
#early_tmax = []
#late_tmax = []
#end_tmax = []

early_mags = []
late_mags = []
end_mags = []
mag_max = []
mag_tmax = []
#early_mag_max = []
#late_mag_max = []
#end_mag_max = []
#early_mag_tmax = []
#late_mag_tmax = []
#end_mag_tmax = []

#loop through each row in rate_array_df, which represents a trial
for i, row in rate_array_df.iterrows():
    #cacluclate the mean of the zscore for each time period
    mean_prestim = np.mean(row.zscore[0:1900])
    mean_early = np.mean(row.zscore[2000:3500])
    mean_late = np.mean(row.zscore[3500:5000])
    mean_end = np.mean(row.zscore[5000:7000])
    #append the means to the lists
    prestim.append(mean_prestim)
    early.append(mean_early)
    late.append(mean_late)
    end.append(mean_end)
    #calculate the max of the zscore for each time period
    #prestim_max_val = np.max(row.zscore[0:1900])
    #early_max_val = np.max(row.zscore[2000:3500])
    #late_max_val = np.max(row.zscore[3500:5000])
    #end_max_val = np.max(row.zscore[5000:7000])
    #append the maxes to the lists
    #prestim_max.append(prestim_max_val)
    #early_max.append(early_max_val)
    #late_max.append(late_max_val)
    #end_max.append(end_max_val)
    #calculate the tmax of the zscore for each time period
    #prestim_tmax_val = np.argmax(row.zscore[0:1900])
    #early_tmax_val = np.argmax(row.zscore[2000:3500])
    #late_tmax_val = np.argmax(row.zscore[3500:5000])
    #end_tmax_val = np.argmax(row.zscore[5000:7000])
    max_val = np.max(row.zscore[2000:7000])
    max.append(max_val)
    tmax_val = np.argmax(row.zscore[2000:7000])
    tmax.append(tmax_val)

    #append the tmaxes to the lists
    #prestim_tmax.append(prestim_tmax_val)
    #early_tmax.append(early_tmax_val)
    #late_tmax.append(late_tmax_val)
    #end_tmax.append(end_tmax_val)
    #calculate the magnitude of the zscore for each time period
    early_mag = abs(mean_early - mean_prestim)
    late_mag = abs(mean_late - mean_prestim)
    end_mag = abs(mean_end - mean_prestim)
    #append the magnitudes to the lists
    early_mags.append(early_mag)
    late_mags.append(late_mag)
    end_mags.append(end_mag)
    #calculate the magnitude for each time index in the time period
    mag_all = abs(row.zscore[2000:7000] - mean_prestim)
    mag_max_val = np.max(mag_all)
    mag_tmax_val = np.argmax(mag_all)
    mag_max.append(mag_max_val)
    mag_tmax.append(mag_tmax_val)
    #early_mag_all = abs(row.zscore[2000:3500] - mean_prestim)
    #late_mag_all = abs(row.zscore[3500:5000] - mean_prestim)
    #end_mag_all = abs(row.zscore[5000:7000] - mean_prestim)
    #calculate the max of the magnitudes
    #early_mag_max_val = np.max(early_mag_all)
    #late_mag_max_val = np.max(late_mag_all)
    #end_mag_max_val = np.max(end_mag_all)
    #append the maxes to the lists
    #early_mag_max.append(early_mag_max_val)
    #late_mag_max.append(late_mag_max_val)
    #end_mag_max.append(end_mag_max_val)
    #calculate the tmax of the magnitudes
    #early_mag_tmax_val = np.argmax(early_mag_all)
    #late_mag_tmax_val = np.argmax(late_mag_all)
    #end_mag_tmax_val = np.argmax(end_mag_all)
    #append the tmaxes to the lists
    #early_mag_tmax.append(early_mag_tmax_val)
    #late_mag_tmax.append(late_mag_tmax_val)
    #end_mag_tmax.append(end_mag_tmax_val)

#add the lists to rate_array_df
rate_array_df['prestim'] = prestim
rate_array_df['early'] = early
rate_array_df['late'] = late
rate_array_df['end'] = end
rate_array_df['max'] = max
rate_array_df['tmax'] = tmax
# rate_array_df['prestim_max'] = prestim_max
# rate_array_df['early_max'] = early_max
# rate_array_df['late_max'] = late_max
# rate_array_df['end_max'] = end_max
# rate_array_df['prestim_tmax'] = prestim_tmax
# rate_array_df['early_tmax'] = early_tmax
# rate_array_df['late_tmax'] = late_tmax
# rate_array_df['end_tmax'] = end_tmax
rate_array_df['early_mag'] = early_mags
rate_array_df['late_mag'] = late_mags
rate_array_df['end_mag'] = end_mags
rate_array_df['mag_max'] = mag_max
rate_array_df['mag_tmax'] = mag_tmax
# rate_array_df['early_mag_max'] = early_mag_max
# rate_array_df['late_mag_max'] = late_mag_max
# rate_array_df['end_mag_max'] = end_mag_max
# rate_array_df['early_mag_tmax'] = early_mag_tmax
# rate_array_df['late_mag_tmax'] = late_mag_tmax
# rate_array_df['end_mag_tmax'] = end_mag_tmax


#%%
import trialwise_analysis as ta
#get rows of rate_array_df that are duplicated
cols = ['rec_dir', 'held_unit_name', 'taste', 'session_trial', 'exp_name', 'exp_group']
rate_array_df = rate_array_df.drop_duplicates(cols)
import scipy.stats as stats
def process_nonlinear_regression(rate_array_df, trial_col = 'session_trial', value_col = 'late_mag'):
    groupings = ['exp_group', 'exp_name', 'taste', 'held_unit_name', 'session']
    params, r2, y_pred = ta.nonlinear_regression(rate_array_df, subject_cols=groupings, trial_col=trial_col, value_col=value_col)
    r2_df = pd.Series(r2).reset_index()
    r2_df = r2_df.reset_index()
    r2_df = r2_df.rename(columns={'level_0':'exp_group', 'level_1':'exp_name', 'level_2': 'taste', 'level_3':'held_unit_name', 'level_4':'session', 0:'r2'})
    r2_df_groupmean = r2_df.groupby(['exp_group', 'taste', 'session']).mean().reset_index()

    modeled = []
    alpha = []
    beta = []
    c = []
    for i, row in rate_array_df.iterrows():
        group = row[groupings]
        pr = params[tuple(group)]
        modeled.append(ta.model(row[trial_col], *pr))
        #yp = y_pred[tuple(group)]
        #modeled.append(y_pred[tuple(group)])
        alpha.append(pr[0])
        beta.append(pr[1])
        c.append(pr[2])
    modeled_str = 'modeled_' + value_col
    rate_array_df[modeled_str] = modeled
    rate_array_df['alpha'] = alpha
    rate_array_df['beta'] = beta
    rate_array_df['c'] = c
    rate_array_df['alpha_pos'] = rate_array_df['alpha'] > 0

    for nm, group in rate_array_df.groupby(groupings):
        trials = group[trial_col].to_numpy()
        model = group[modeled_str].to_numpy()
        trial_diff = np.diff(trials)
        model_diff = model[-1] - model[0]
        alpha = group['alpha'].to_numpy()
        alpha = alpha[0]

        yp = y_pred[tuple(nm)]
        ypdiff = yp[-1] - yp[0]

        if alpha > 0 and model_diff < 0:
            print('alpha is positive and model is decreasing')
            print(nm)
            print(ypdiff)
        elif alpha < 0 and model_diff > 0:
            print('alpha is negative and model is increasing')
            print(nm)
            print(ypdiff)


    #sort the df by groupings and session_trial
    #rate_array_df = rate_array_df.sort_values(by=groupings+[time_col]).reset_index(drop=True)

    #ta.plot_fits(rate_array_df, trial_col=trial_col, dat_col=value_col, model_col=modeled_str, time_col='session', save_dir=PA.save_dir)

    shuff = ta.iter_shuffle(rate_array_df, niter=100, subject_cols=groupings, trial_col=trial_col, value_col=value_col, save_dir=PA.save_dir, overwrite=False) #TODO break this down by group

    #calculate p-value for each unique held_unit_name in shuff
    names = []
    pvals = []
    for name, group in shuff.groupby(['exp_group', 'exp_name', 'taste', 'held_unit_name', 'session']):
        #get r2 for corresponding group in r2_df
        row = r2_df.loc[(r2_df.exp_group == name[0]) & (r2_df.exp_name == name[1]) & (r2_df.taste == name[2]) & (r2_df.held_unit_name == name[3]) & (r2_df.session == name[4])]
        p_value = np.mean(group.r2.to_numpy() >= row.r2.to_numpy())
        pvals.append(p_value)
        names.append(name)

    pval_df = pd.DataFrame(names, columns=['exp_group', 'exp_name', 'taste', 'held_unit_name', 'session'])
    pval_df['pval'] = pvals

    #merge pval_df into r2_df
    r2_df = r2_df.merge(pval_df, on=['exp_group', 'exp_name', 'taste', 'held_unit_name', 'session'])
    #filter just the rows where pval < 0.05
    sig_rows = r2_df.loc[r2_df.pval < 0.05]
    sig_units = sig_rows.held_unit_name.unique()

    #create versions of r2_df, rate_array_df and shuff that only have the significant units
    rate_array_df_sig = rate_array_df[rate_array_df.held_unit_name.isin(sig_units)]
    shuff_sig = shuff[shuff.held_unit_name.isin(sig_units)]
    r2_df_sig = r2_df[r2_df.held_unit_name.isin(sig_units)]
    r2_df_groupmean_sig = r2_df.groupby(['exp_group', 'taste', 'session']).mean().reset_index()


    #save shuff as feather datafr
    avg_shuff_sig = shuff_sig.groupby(['exp_group', 'session', 'taste', 'iternum']).mean().reset_index()
    #%% plot the r2 values for each session with the null distribution
    save_flag = trial_col + '_' + value_col
    ta.plot_null_dist(avg_shuff_sig, r2_df_groupmean_sig, save_flag=save_flag, save_dir=PA.save_dir)
    ta.plot_fits_summary(rate_array_df_sig, trial_col=trial_col, dat_col=value_col, model_col=modeled_str, time_col='session', save_dir=PA.save_dir)


trial_cols = ['session_trial', 'taste_trial']
value_cols = ['prestim', 'early', 'late', 'end',
              'late_mag', 'early_mag', 'end_mag']
value_cols = ['max', 'tmax', 'mag_max', 'mag_tmax']
# value_cols = ['prestim_max', 'early_max', 'late_max', 'end_max',
#               'prestim_tmax', 'early_tmax', 'late_tmax', 'end_tmax',
#               'early_mag_max', 'late_mag_max', 'end_mag_max',
#               'early_mag_tmax', 'late_mag_tmax', 'end_mag_tmax']

for trial_col in trial_cols:
    for value_col in value_cols:
        process_nonlinear_regression(rate_array_df, trial_col=trial_col, value_col=value_col)

def load_shuff(PA, trial_col, value_col):
    save_flag = trial_col + '_' + value_col
    shuff = pd.read_feather(os.path.join(PA.save_dir, save_flag + '_shuff.feather'))
    r2_df_groupmean = pd.read_feather(os.path.join(PA.save_dir, save_flag + '_r2_df_groupmean.feather'))
    return shuff, r2_df_groupmean



g = sns.lmplot(data=rate_array_df, x='trial', y='early_mag', hue='exp_group', col='session', row='din', height=4, aspect=.7, x_estimator=np.mean, facet_kws={'margin_titles':True})
plt.show(g)

h = sns.lmplot(data=rate_array_df, x='trial', y='late_mag', hue='exp_group', col='session', row='din', height=4, aspect=.7, x_estimator=np.mean, facet_kws={'margin_titles':True})
plt.show(h)


HA = ana.HmmAnalysis(proj)
ov = HA.get_hmm_overview(overwrite=False) #get the hmm_overview dataframe
sorted = HA.sort_hmms_by_AIC(overwrite=False) #get hmm_overview sorted by best AIC
best_hmms = HA.get_best_hmms(sorting='best_AIC', overwrite=False) #get rows of hmm_overview where sorting column==sorting arugument
#make a subset of best hmms that is justhte variables that I'm grouping on and the varibales I want to merge in.
#get the columns that are overlapping
best_hmms_din = best_hmms.rename(columns={'channel': 'din'})
common_cols = list(set(rate_array_df.columns).intersection(best_hmms_din.columns))
cols_to_merge = common_cols + ['hmm_id', 'prestim', 'early', 'late']
best_hmms_tomerge = best_hmms_din[cols_to_merge].copy().drop_duplicates().reset_index()

#b4 this: merge in the hmm ID from best hmms into df by asking chatgpt how to do a "left join"
df = df.merge(best_hmms_tomerge, on=common_cols, how='left')

dfs = []
#fix the session trial column, group by rec_dir, and subtract session trial from the min session trial of that col
for name, group in df.groupby(['rec_dir']):
    group['session_trial'] = group['session_trial'] - min(group['session_trial'])
    dfs.append(group)
df = pd.concat(dfs)


def convert_columns_to_float(df): #this function does nothing at the moment
    '''converts all possible columns into floats'''
    
    # Loop through the columns
    for col in df.columns:
        try:
            # Try to convert the column to floats
            df[col] = df[col].astype(float)
            print(f'{col} converted')
        except ValueError:
            # If the conversion fails, skip the column
            continue
    
    return df
x = convert_columns_to_float(df)

def find_hashable_cols(df): #returns an empty list as of now
    hashable_columns = []
    for col in df.columns:
        try:
            if isinstance(df[col].apply(hash), int):
                hashable_columns.append(col)
        except:
            pass
    return hashable_columns

def check_valid_trial(i, j, fr):
    '''meant to be used in the following loop to create a df with firing rates (frs)
    given a fr tuple returned from hmma.get_state_firing_rates, 
    determine there is a number in the array that ==i, meaning that this trial has a fr
    '''
    #for a 2d array its array[row][col], so its fr[trial][neuron]
    if i in fr[1]:
        return fr[0][i][j]
    else:
        return 'no hmm' #this is the same as returning nan, but it needs to be this way for the loop

#from best hmms also get the state and add it in with the left join (prestim, early late) but just do late state for now

#time it
start = timeit.default_timer()

input_df = df[['rec_dir', 'din', 'hmm_id', 'prestim', 'early', 'late', 'unit_num']]
input_fr_df = pd.DataFrame(columns=['rec_dir', 'hmm_id', 'prestim', 'early', 'late', 'din', 'trial', 'prestim_firing_rate', 'early_firing_rate', 'late_firing_rate', 'unit_num'])
#loop through every unique combo of rec_dir, din, hmmid 
prestim_frs = early_frs = []
for name, group in input_df.groupby(['rec_dir', 'din', 'hmm_id', 'prestim', 'early', 'late']): #maybe don't group
    #for the late state
    #use the info in fr to create a df
    late_fr = hmma.get_state_firing_rates(name[0], name[2], name[5])
    
    #get the unit number
    dat = blechpy.load_dataset(name[0])
    unit_table = dat.get_unit_table()
    # in fr each row is trial each column is neuron
        #the list along with it is trials
    late_trial_list = late_fr[1]
    late_spiking_df = late_fr[0]      
    #because the next loop gets rows instead of columns, transpose the spiking_df to iterate over trials with the same unit_num
    late_spiking_dfT = late_spiking_df.T
    #now, its unit_num on the y axis and 
    #create an index for trials because the spiking_df was transposed
    
    #repeat for prestim and early
    prestim_fr = hmma.get_state_firing_rates(name[0], name[2], name[3])
    prestim_trial_list = prestim_fr[1]
    prestim_spiking_df = prestim_fr[0]
    prestim_spiking_dfT = prestim_spiking_df.T
    
    early_fr = hmma.get_state_firing_rates(name[0], name[2], name[4])
    early_trial_list = early_fr[1]
    early_spiking_df = early_fr[0]
    early_spiking_dfT = early_spiking_df.T
    
    #the next loop is to loop through the trials
    
    #if a trial is missing firing rates, add adjust it to not mess up the indexing
    prestim_missing=early_missing=late_missing=0
    j=0
    for i in range(0, 30): # this works because there are 30 trials for each taste

        if False: #check if all of the sizes of the spiking dfs are the same. Rn it is false to save time
            if not np.shape(prestim_spiking_df)[1] == np.shape(early_spiking_df)[1] ==np.shape(late_spiking_df)[1]:
                print(f'possible source of error: the number of neurons in trial #{i} are not the recorded same in the recorded hmm firing rates')
        #try and except blocks are for when the i index is out of range, because if there 
        #is a trial missing then the height of the fr df will be 1 less, meaning the index
        #will be out of range
        try:
            if check_valid_trial(i, j, prestim_fr)=='no hmm':
                prestim_missing +=1
        except:
            pass
        
        try:
            if check_valid_trial(i, j, early_fr)=='no hmm':
                early_missing +=1
        except:
            pass
        
        try:        
            if check_valid_trial(i, j, late_fr)=='no hmm':
                late_missing +=1
        except:
            pass                
            
        #now to loop through the neurons
        for j in range(np.shape(prestim_spiking_df)[1]):
            prestim_firing_rate = check_valid_trial(i-prestim_missing, j, prestim_fr)
            early_firing_rate = check_valid_trial(i-early_missing, j, early_fr)
            late_firing_rate = check_valid_trial(i-late_missing, j, late_fr)
            
            trial_num= i
            unit_name=unit_table['unit_name'][j]
            
            input_fr_df.loc[len(input_fr_df)] = [name[0], name[2], name[3], name[4], name[5], name[1], trial_num, prestim_firing_rate, early_firing_rate, late_firing_rate, unit_name]
    print(f'{name[0]}, {name[1]}, {name[2]}, {name[3]}, {name[4]}, {name[5]} hmm firing rates obtained')
    
dep_vars = ['prestim_firing_rate', 'early_firing_rate', 'late_firing_rate']
for var in dep_vars:
    input_fr_df[var] = pd.to_numeric(input_fr_df[var], errors='coerce')

fr_df_loop_time = timeit.default_timer()
print(f'The loop to extract hmms took: {fr_df_loop_time - start:.6f} seconds')

#this creates a list in each row that goes [1, 2, 3, 4... for the lenth of the firing rate list
#fr_df['neuron_index'] = [[j for j in range(1, len(fr_df['firing_rate'][i])+1)] for i in range(len(fr_df['firing_rate']))]

#expland the df_fr "fring_rate" col


#also, neuron shold be group edby rec_dir
input_fr_df['trial'] = input_fr_df['trial'].astype(int)

# in fr_df2 convert it to an int and change it to "trial_num" (I think) so it matches df
df = df.rename(columns={"trial_num": "trial"})

    #quality of life changes to make the data more readable
DinToTasteDict = {'din': [0, 1, 2, 3, 4], 'taste': ['Suc', 'NaCl', 'CA', 'QHCl', 'Spont']}

DinToTaste = pd.DataFrame(DinToTasteDict)
df = df.merge(DinToTaste, on=['din'])

df['Day'] = df['rec_num']
#delete rec_num
df = df.drop(['rec_num'], axis=1)

#For some reason, in DS46 day 2 CA trials are not in best Hmms, so they are Nans in df right now
#this line is to take out the nan rows
df = df.dropna()

df = df.drop_duplicates(['session_trial', 'held_unit_name', 'taste_trial', 'exp_name', 'rec_name', 'exp_group', 'rec_group', 'exp_dir'])
df['ones']=1
df['trial'] = df.groupby(['rec_dir', 'held_unit_name', 'taste', 'interJ3'])['ones'].cumsum()
df = df.drop(['ones'], axis=1)
#drop the inter_J column because it is causing problems 
#there needs to be a day 1-2 interJ and day 2-3 interJ, but for no wlets delete it
pass 
'''soltions: 

    add a single column that either has a float "0.1345" or a string "0.1453-0.342" for held between 2 days or 3 days


    create another dataframe that stores this data and use it to add to other graphs
'''
df = df.drop('interJ3', axis=1)

#convert all of the objects to integers and floats
cols_to_convert_toint = ['session_trial', 'held_unit_name', 'taste_trial', 'late', 'hmm_id', 'trial', 'Day']
cols_to_convert_tofloat = []

df = df.drop_duplicates(cols_to_convert_tofloat + cols_to_convert_toint)
for col in cols_to_convert_toint:
    df[col] = df[col].astype(int)
    

for col in cols_to_convert_tofloat:
    df[col] = df[col].astype(float)

#then merge them
df = df.merge(input_fr_df, how='left', on= list(set(df.columns).intersection(input_fr_df.columns)))

#get the # of spikes from (2,000-4,000)/2 in each spike array and make that a new column called responce_rate
def getSpikingRate(df, begining, end):
    '''returns the spikin' rate for given miliseconds, requires that the df has 
    a colunm named 'spike_array in a 1 dimentional list'''
    spikesAcrossRows = [] #[14 spikes in row 1, 35 spikes in row 2 etc]
    for spikeTrain in df['spike_array']:
        spikes = 0
        for num in spikeTrain[begining-1:end]:
            if num == 1:
                spikes+=1
        spikesAcrossRows.append(spikes)
    divisor = (end-begining)/1000 #how many seconds passed during this time?
    spikesAcrossColumns = [x/divisor for x in spikesAcrossRows] #apply the divisor
    return spikesAcrossColumns

#get the start and end times of the state of interest from the HMMs


def getSpikingRateHmm():
    
    pass #use hmm_analysis.get_state_firing_rates(rec_dir, hmm_id, state, units=unit)
    #variables I need
    '''
    Rec dir is the recodring directory of the ds in the following df
    
    to get hmm_id and state:
        best_HMMs = HA.get_best_hmms(sorting = 'best_BIC') #creates the df
   
    hmm_id is a column in best_HMMs indexed by recodring directory
        go row by row and index through what you need with apply funciton or loop
        
    for each combo of rec dir and taste (this is a row) there are 3 colunms to get, I should get 3 different firing rates ('prestim', 'early', 'late')
    
    Pass the prestim, early or late for "state" in the get_state_fr function, this will return the same prestim early or late firing rates
    
    First, just do late firing rates to output, and then do the others.
    
    units should equal the number of the neuron that is being analyzed in the 1st loop, which is through a unit table
        the held unit table willl have a unit number
        

    '''



sd = os.path.join(PA.save_dir, 'trialwise_held_unit_responses')
try:
    os.mkdir(sd)
except: pass


dep_vars = ['prestim_firing_rate', 'early_firing_rate', 'late_firing_rate']
#columns that aren't the dep vars
other_vars = list(df.columns)
for var in dep_vars:
    if var in other_vars:
        other_vars.remove(var)

#time it
start = timeit.default_timer()

graphdf = df.loc[df.din != 4] #getrid of the control
graphdf = df.melt(id_vars = other_vars, value_vars=dep_vars, var_name='epoch', value_name='firing_rate')

df = df.melt(id_vars = other_vars, value_vars=dep_vars, var_name='epoch', value_name='firing_rate')

replace_dict = {dep_vars[0]:'prestim', dep_vars[1]:'early', dep_vars[2]:'late'}
graphdf['epoch'] = graphdf['epoch'].replace(replace_dict)

if False: #makes plots of spikngrateXtrialand spiking rateXsession_trial
    '''Session trial counts how many times any taste has been given to the rat, while 
    trial counts the times that a specific taste has been given
'''
    for taste in graphdf['taste'].unique():
        for name, group in graphdf.groupby(['held_unit_name', 'exp_name']):
            
            
            pn = taste+str(name[0]) + name[1] + 'trials'+'.svg'
            sf = os.path.join(sd, pn)
            g=sns.lmplot(data=group, x='trial', y='firing_rate', row='epoch', col='Day', hue='exp_group') #what is taste tringto pull here
            g.savefig(sf)
            plt.close("all")
        for name, group in graphdf.groupby(['held_unit_name', 'exp_name']):
            
            pn = taste+str(int(name[0])) + name[1] + 'sesson_trials'+'.svg'
            sf = os.path.join(sd, pn)
            g=sns.lmplot(data=group, x='session_trial', y='firing_rate', row='epoch', col='Day', hue='exp_group') #what is taste tringto pull here
            g.savefig(sf)
            plt.close("all")


#timer results
graph1_loop_time = timeit.default_timer()
print(f'Creating scatterplots for spiking rate took: {graph1_loop_time - start:.6f} seconds')


'''pearson df correlating spiking rate across
days
epochs
unit_num
exp_name
session_trial/taste_trial (make 2 different dfs)
'''
#taste_trial first

from scipy.stats import pearsonr

# create an empty DataFrame to store the results
trial_pearson_df = pd.DataFrame(columns=['Day', 'epoch', 'unit_num', 'exp_name', 'taste', 'r', 'r^2', 'p'])

# group the data by the specified columns
for name, group in df.groupby(['Day', 'epoch', 'unit_num', 'exp_name', 'taste']):
    #replace nans in firing rate with 0
    group['firing_rate'] = group['firing_rate'].replace(np.nan,0)
    # calculate the Pearson correlation between 'var' and 'taste_trial' for each group
    r, p = pearsonr(group['trial'], group['firing_rate'])
    rsq = r**2
    # add results to df
    trial_pearson_df.loc[len(trial_pearson_df)] = [name[0], name[1], name[2], name[3], name[4], r, rsq, p]

#now do the same above but for session trual
# create an empty DataFrame to store the results
sestrial_pearson_df = pd.DataFrame(columns=['Day', 'epoch', 'unit_num', 'exp_name', 'taste', 'exp_group', 'r', 'r^2', 'p'])
#session trial pearson df
# group the data by the specified columns
for name, group in df.groupby(['Day', 'epoch', 'unit_num', 'exp_name', 'taste']):
    #replace nans in firing rate with 0
    group['firing_rate'] = group['firing_rate'].replace(np.nan,0)
    # calculate the Pearson correlation between 'var' and 'taste_trial' for each group
    r, p = pearsonr(group['session_trial'], group['firing_rate'])
    rsq = r**2
    # add results to df
    sestrial_pearson_df.loc[len(sestrial_pearson_df)] = [name[0], name[1], name[2], name[3], name[4], group['exp_group'].tolist()[0], r, rsq, p]
#add if the p is sig for me :)
sestrial_pearson_df['sig'] = (sestrial_pearson_df['p']<=0.05) | (sestrial_pearson_df['p']>=0.95)

#now, get the mean and stdev of the r^2 vals for each group

sestrial_avg_pearson_df = sestrial_pearson_df.groupby(['exp_group', 'taste', 'Day', 'epoch']).mean()
sestrial_avg_pearson_df = sestrial_avg_pearson_df.rename(columns={"r": "r_avg", "r^2": "r^2_avg", "sig":"sig_avg", "p":"p_avg"})
sestrial_std_pearson_df = sestrial_pearson_df.groupby(['exp_group', 'taste', 'Day', 'epoch']).std()
sestrial_std_pearson_df = sestrial_std_pearson_df.rename(columns={"r": "r_std", "r^2":"r^2_std", "sig":"sig_std", "p":"p_std"})

sestrial_descripives_pearson_df = sestrial_avg_pearson_df.join(sestrial_std_pearson_df)


''' this plot has a very mysterious error
plt.figure(figsize=(20, 20))
g = sns.catplot(x="Day", y="r^2", hue="exp_group", col="epoch",row='taste',
                data=sestrial_pearson_df.dropna(), kind="box", margin_titles=False,
                palette=["#FFA7A0", "#ABEAC9"],
                height=4, aspect=.7)
g.map_dataframe(sns.stripplot, x="Day", y="r^2", hue="exp_group")
g.set_axis_labels("Day", "r^2")

# set margin
plt.subplots_adjust(top=0.92)
g.fig.suptitle('Title of plot', fontsize=16)

# save figure
g.savefig('/home/senecascott/Documents/CodeVault/experience_analysis/testfigr^2.png', dpi=500)
plt.close("all")


g = sns.catplot(x="Day", y="r^2", hue="exp_group", col="epoch",
                data=sestrial_pearson_df.dropna(), kind="box",
                palette=["#FFA7A0", "#ABEAC9"],
                height=4, aspect=.7);
g.map_dataframe(sns.stripplot, x="Day", y="r^2", 
                hue="exp_group", palette=["#404040"], 
                alpha=0.6, dodge=True)
# g.map(sns.stripplot, "sex", "total_bill", "smoker", 
#       palette=["#404040"], alpha=0.6, dodge=True)
plt.show()
'''


#back to the df, now we donna divide trial by 5 no remainder to make a trial group
#and in that trial group take the avd firing rate, then plot group x fr_avg

#get the group that each trial is in

# Define the bins for the trial groups
bins = [1, 5, 10, 15, 20, 25, 30]

# Define the labels for the trial groups
labels = [1, 2, 3, 4, 5, 6]

# Use pd.cut to assign each trial to a trial group based on the bins and labels
df['trial_group'] = pd.cut(df['trial'], bins=bins, labels=labels)
#for some reason there are nans where there should be 1 becasue trial(1) = trial_group(1)
df['trial_group'] = df['trial_group'].fillna(1)

#make a graph using this as the x axis:
for name, group in df.groupby(['taste']):
    pn = str(name[0])+ 'grouped_trials'+'.svg'
    sf = os.path.join(sd, pn)
    g=sns.relplot(data=group, x='trial_group', y='firing_rate', row='epoch', col='Day', hue='exp_group', kind='line', legend='brief', facet_kws={"margin_titles":True}) #what is taste tringto pull here
    g.savefig(f'/home/senecascott/Documents/CodeVault/experience_analysis/{name}grouped_trials.svg')

#b/c dan expects this to be super variable, z score the firing rates grouped by neuron (held_unit_name)

#create a z score column
df['firing_rateZ'] = df.groupby(['held_unit_name', 'taste'])['firing_rate'].transform(lambda x: (x - np.mean(x)) / np.std(x))

#make a graph using this as the x axis:
for name, group in df.groupby(['taste']):
    pn = str(name[0])+ 'grouped_trials'+'.svg'
    sf = os.path.join(sd, pn)
    g=sns.relplot(data=group, x='trial_group', y='firing_rateZ', row='epoch', col='Day', hue='exp_group', kind='line', facet_kws={"margin_titles":True}) #what is taste tringto pull here
    g.savefig(f'/home/senecascott/Documents/CodeVault/experience_analysis/grouped_trials_zscore{name}.svg')
plt.close("all")

#make a column with abs values of the z score
df['abs_firing_rateZ'] = abs(df['firing_rateZ'])
for name, group in df.groupby(['taste']):
    pn = str(name[0])+ 'grouped_trials'+'.svg'
    sf = os.path.join(sd, pn)
    g=sns.relplot(data=group, x='trial_group', y='abs_firing_rateZ', row='epoch', col='Day', hue='exp_group', kind='line', facet_kws={"margin_titles":True}) #what is taste tringto pull here
    #add a title
    g.fig.suptitle('Firing_rates Absolute valued & Z scored across held units', fontsize=20) # set the title for the entire figure
    g.fig.subplots_adjust(top=0.9)
    g.savefig(f'/home/senecascott/Documents/CodeVault/experience_analysis/grouped_trials_abs_zscore{name}.svg')
plt.close("all")

#%% numpy cross correlations
import numpy as np
import matplotlib.pyplot as plt

# Define two spike trains with 100 spikes each
spike_train1 = np.random.randint(0, 1000, size=100)
spike_train2 = np.random.randint(0, 1000, size=100)

# Compute the cross-correlation function using numpy's correlate function
cross_corr = np.correlate(spike_train1, spike_train2, mode='full')

# Plot the cross-correlation histogram
plt.plot(cross_corr)
plt.title('Cross-Correlation Histogram')
plt.xlabel('Time Lag')
plt.ylabel('Number of Spikes')
plt.show()




#%% Elephant nonsense

#corss correlations for spikes, not controlling for HMM states, so all states at once

import elephant
import neo
import quantities as pq
from elephant.conversion import BinnedSpikeTrain
import quantities as pq
import numpy as np
from elephant.conversion import BinnedSpikeTrain
from elephant.spike_train_generation import StationaryPoissonProcess
from elephant.spike_train_correlation import cross_correlation_histogram
import numpy as np
import elephant.spike_train_correlation as stc

spiketrain = neo.SpikeTrain(df.spike_array[1], t_stop = len(df.spike_array[1])/1000, units='s')
#binnned spike train
bst = BinnedSpikeTrain(spiketrain, bin_size=0.001 * pq.s)

# Calculate the cross-correlation histogram between the two spike trains
cc_hist = stc.cross_correlation_histogram(BinnedSpikeTrain, BinnedSpikeTrain)

print(cc_hist)

'''
TO DO:
    put your thinking cap on [|:>    

figure out what the avg firing rate is for each state 

'''

import elephant

import quantities as pq

import numpy as np

from elephant.conversion import BinnedSpikeTrain

from elephant.spike_train_generation import StationaryPoissonProcess

from elephant.spike_train_correlation import cross_correlation_histogram
np.random.seed(1)

binned_spiketrain_i = BinnedSpikeTrain(

       StationaryPoissonProcess(

           10. * pq.Hz, t_start=0 * pq.ms, t_stop=5000 * pq.ms).generate_spiketrain(),

       bin_size=5. * pq.ms)

binned_spiketrain_j = BinnedSpikeTrain(

       StationaryPoissonProcess(

           10. * pq.Hz, t_start=0 * pq.ms, t_stop=5000 * pq.ms).generate_spiketrain(),

       bin_size=5. * pq.ms)
cc_hist, lags = cross_correlation_histogram(

       binned_spiketrain_i, binned_spiketrain_j, window=[-10, 10],

       border_correction=False,

       binary=False, kernel=None)






