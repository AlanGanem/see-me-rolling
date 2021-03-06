# AUTOGENERATED! DO NOT EDIT! File to edit: notebooks_dev/rolling.ipynb (unless otherwise specified).

__all__ = ['make_generic_rolling_features', 'make_generic_resampling_and_shift_features',
           'create_rolling_resampled_features', 'make_generic_rolling_features',
           'make_generic_resampling_and_shift_features', 'create_rolling_resampled_features']

# Cell
from functools import reduce, partial
import os
import datetime as dt
from tqdm import tqdm
from warnings import warn

import pandas as pd
import numpy as np
import numba

from dask import dataframe as dd
from dask import delayed
from dask.diagnostics import ProgressBar


# Cell

def _get_index_rolling_windows(rolling_obj):
    '''
    get positional indexes of rows of each rolling window
    '''

    if hasattr(rolling_obj, '_selection'):
        previous_selection = getattr(rolling_obj, '_selection')
    else:
        previous_selection = None

    INDEX_LIST = []
    #define function to append values to global INDEX_LIST since rolling apply won't let return arrays
    def f(x): INDEX_LIST.append(x.astype(int)); return 0
    assert '__indexer__' not in rolling_obj.obj.columns, 'DataFrame should not contain any col with "__indexer__" name'
    rolling_obj.obj = rolling_obj.obj.assign(__indexer__ = np.arange(len(rolling_obj.obj)), inplace = True)
    rolling_obj._selection = '__indexer__'
    rolling_obj.apply(f, raw = True)
    rolling_obj.obj = rolling_obj.obj.drop(columns = ['__indexer__'])

    delattr(rolling_obj, '_selection')

    if not previous_selection is None:
        setattr(rolling_obj, '_selection', previous_selection)

    return INDEX_LIST


def _apply_custom_rolling(rolling_obj, func, raw = True, engine = 'numpy', *args, **kwargs):

    engines = {
        'numpy':_rolling_apply_custom_agg_numpy,
        'pandas':_rolling_apply_custom_agg_pandas,
        'numba':_rolling_apply_custom_agg_numpy_jit
    }
    _rolling_apply = engines[engine]

    indexes = _get_index_rolling_windows(rolling_obj)
    if hasattr(rolling_obj, '_selection'):
        if getattr(rolling_obj, '_selection') is None:
            values = _rolling_apply(rolling_obj.obj, indexes, func, *args, **kwargs)

        values = _rolling_apply(rolling_obj.obj[rolling_obj._selection], indexes, func, *args, **kwargs)
    else:
        values = _rolling_apply(rolling_obj.obj, indexes, func, *args, **kwargs)

    return values



def _rolling_apply_custom_agg_numpy_jit(df, indexes, func):
    '''
    applies some aggregation function over groups defined by index.
    groups are numpy arrays
    '''

    dfv = df.values
    # template of output to create empty array
    #use this for jit version
    shape = np.array(func(dfv[:1])).shape
    #d = [np.empty(*shape) for _ in  range(len(indexes))]
    result_array = np.empty((len(indexes),*shape))

    @numba.jit(forceobj=True)
    def _roll_apply(dfv, indexes, func, result_array):
        for i in np.arange(len(indexes)):
            data = dfv[indexes[i]]
            if len(data) > 0:
                result = func(data)
                result_array[i] = result
            else:
                result = np.empty(shape)


        return result_array

    return _roll_apply(dfv, indexes, func, result_array)


def _rolling_apply_custom_agg_numpy(df, indexes, func, *args, **kwargs):
    '''
    applies some aggregation function over groups defined by index.
    groups are numpy arrays
    '''

    dfv = df.values
    d = [[] for _ in range(len(indexes))]
    for i in tqdm(range(len(indexes))):
        data = dfv[indexes[i]]
        if len(data) > 0:
            result = func(data, *args, **kwargs)
            d[i] = result

    return d

def _rolling_apply_custom_agg_pandas(df, indexes, func, *args, **kwargs):
    '''
    applies some aggregation function over groups defined by index.
    groups are pandas dataframes
    '''

    # template of output to create empty array
    d = [[] for _ in range(len(indexes))]

    for i in tqdm(range(len(indexes))):
        data = df.iloc[indexes[i]]
        if len(data) > 0:
            result = func(data, *args, **kwargs)
            d[i] = result

    return pd.concat(d)

# Cell
def _make_rolling_groupby_object(df, group_columns, date_column):
    '''
    helping function to make computational graph creation faster
    '''
    groupby_object = df.set_index(date_column).groupby(group_columns)

    return groupby_object

def make_generic_rolling_features(
    df,
    calculate_columns,
    group_columns,
    date_column,
    suffix = None,
    rolling_operation = 'mean',
    window = '60D',
    min_periods=None,
    center=False,
    win_type=None,
    on=None,
    axis=0,
    closed=None,
    **rolling_operation_kwargs
):
    '''
    make generic/custom rolling opeartion for a given column, grouped by customer, having Data de Emissao as date index
    if calculate cols is None, than use all cols

    Parameters
    ----------

    df: DataFrame
        DataFrame to make rolling features over

    calculate_columns: list of str
        list of columns to perform rolling_operation over

    group_columns: list of str
        list of columns passed to GroupBy operator prior to rolling

    date_column: str
        datetime column to roll over

    suffix: Str
        suffix for features names

    rolling_operation: Str of aggregation function, deafult = "mean"
        str representing groupby object method, such as mean, var, quantile ...

    window:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    min_periods:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    center:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    win_type:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    on:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    axis:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    closed:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    rolling_operation_kwargs:
        key word arguments passed to rolling_operation

    Returns
    -------
    DataFrame with the new calculated features
    '''

    assert group_columns.__class__ in (set, tuple, list), 'group_columns type should be one of (tuple, list, set), not {group_columns.__class__}'
    if calculate_columns is None:
        calculate_columns = [i for i in df.columns if not i in [*group_columns, date_column]]

    keep_columns = [*group_columns, date_column, *calculate_columns]

    if not isinstance(df,(
        dd.groupby.DataFrameGroupBy,
        pd.core.groupby.generic.DataFrameGroupBy,
        pd.core.groupby.generic.SeriesGroupBy,
        dd.groupby.SeriesGroupBy
    )):

        df = _make_rolling_groupby_object(df, group_columns, date_column)

    if isinstance(df, (pd.core.groupby.generic.DataFrameGroupBy, pd.core.groupby.generic.SeriesGroupBy)):


        df = getattr(
            df[calculate_columns]
            .rolling(
                window = window,
                min_periods=min_periods,
                center=center,
                win_type=win_type,
                on=on,
                axis=axis,
                closed=closed
            ),
            rolling_operation,

        )(**rolling_operation_kwargs).reset_index()

    else: #syntax for dask groupby rolling

        df = df[calculate_columns].apply(
                lambda x: getattr(
                    x.sort_index().rolling(
                        window = window,
                        min_periods=min_periods,
                        center=center,
                        win_type=win_type,
                        on=on,
                        axis=axis,
                        closed=closed
                    ),
                    rolling_operation,
                )(**rolling_operation_kwargs).reset_index()
            #meta = meta, #works only for float rolling

            ).reset_index().drop(columns = [f'level_{len(group_columns)}']) #drop unwanted "level_n" cols


    if not suffix:

        df.columns = [
            f'{col}__rolling_{rolling_operation}_{window}_{str(rolling_operation_kwargs)}'
            if not col in (*group_columns, date_column) else col
            for col in df.columns
        ]
    else:
        df.columns = [
            f'{col}__rolling_{window}_{suffix}'
            if not col in (*group_columns, date_column) else col
            for col in df.columns
        ]

    return df

def _make_shift_resample_groupby_object(df, group_columns, date_column,freq, n_periods_shift):

    groupby_object = (
            df
            .assign(**{date_column:df[date_column] + pd.Timedelta(n_periods_shift,freq)}) #shift
            .set_index(date_column)
            .groupby([*group_columns, pd.Grouper(freq = freq)])
        )
    return groupby_object

def make_generic_resampling_and_shift_features(
    df, calculate_columns, group_columns, date_column, freq = 'm',
    agg = 'last', n_periods_shift = 0, assert_frequency = False, suffix = '',**agg_kwargs
):

    '''
    makes generic resamples (aggregates by time frequency) on column.
    shifts one period up to avoid information leakage.
    Doing this through this function, although imposing some limitations to resampling periods, is much more efficient than
    pandas datetime-set_index + groupby + resampling.

    Parameters
    ----------

    df: DataFrame
        DataFrame to make rolling features over

    calculate_columns: list of str
        list of columns to perform rolling_operation over

    group_columns: list of str
        list of columns passed to GroupBy operator prior to rolling

    date_column: str
        datetime column to roll over

    freq: valid pandas freq str:
        frequency to resample data

    agg: Str of aggregation function, deafult = "last"
        str representing groupby object method, such as mean, var, last ...

    n_periods_shift: int
        number of periods to perform the shift opeartion. shifting is important after aggregation to avoid information leakage
        e.g. assuming you have the information of the end of the month in the beggining of the month.

    assert_frequency: bool, default = False
        resamples data to match freq, using foward fill method for
        missing values

    suffix: Str
        suffix for features names

    agg_kwargs:
        key word arguments passed to agg

    Returns
    -------
    DataFrame with the new calculated features
    '''

    if calculate_columns is None:
        calculate_columns = [i for i in df.columns if not i in [*group_columns, date_column]]

    keep_columns = [*group_columns, date_column, *calculate_columns]

    df = (
        df
        .assign(**{date_column:df[date_column] + pd.Timedelta(n_periods_shift,freq)}) #shift
        .set_index(date_column)
        .groupby([*group_columns, pd.Grouper(freq = freq)])
    )


    if isinstance(agg, str):
        df = getattr(df[calculate_columns], agg)(**agg_kwargs)
    else:
        df = df[calculate_columns].apply(lambda x: agg(x,**agg_kwargs))


    if not suffix:
        df.columns = [f'{i}__{str(agg)}_{str(agg_kwargs)}' for i in df.columns]
    else:
        df.columns = [f'{i}__{suffix}' for i in df.columns]

    #create new shifted date_col
    #df.loc[:, date_column] = date_col_values


    if assert_frequency:
        df = df.reset_index()
        df = df.set_index(date_column).groupby(group_columns).resample(freq).fillna(method = 'ffill')


    resetable_indexes = list(set(df.index.names) - set(df.columns))
    df = df.reset_index(level = resetable_indexes)
    df = df.reset_index(drop = True)

    return df


def create_rolling_resampled_features(
    df,
    calculate_columns,
    group_columns,
    date_column,
    extra_columns = [],
    n_periods_shift = 1,
    rolling_first = True,
    rolling_operation = 'mean',
    window = '60D',
    resample_freq = 'm',
    resample_agg = 'last',
    assert_frequency = False,
    rolling_suffix = '',
    resample_suffix = '',
    min_periods=None,
    center=False,
    win_type=None,
    on=None,
    axis=0,
    closed=None,
    rolling_operation_kwargs = {},
    resample_agg_kwargs = {}
):
    '''
    calculates rolling features groupwise, than resamples according to resample period.
    calculations can be done the other way arround if rolling_first is set to False

    Parameters
    ----------


    df: DataFrame
        DataFrame to make rolling features over

    calculate_columns: list of str
        list of columns to perform rolling_operation over

    group_columns: list of str
        list of columns passed to GroupBy operator prior to rolling

    date_column: str
        datetime column to roll over

    extra_columns: list of str
        list of extra columns to be passed to the final dataframe without aggregation (takes the last values, assumes they're constant along groupby).
        usefull to pass merge keys

    n_periods_shift: int
        number of periods to perform the shift opeartion. shifting is important after aggregation to avoid information leakage
        e.g. assuming you have the information of the end of the month in the beggining of the month.

    rolling_first: bool, deafult = True
        whether to perform rolling before resampling, or the other way arround

    rolling_operation: Str of aggregation function, deafult = "mean"
        str representing groupby object method, such as mean, var, quantile ...

    window:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    resample_freq: valid pandas freq str:
        frequency to resample data

    resample_agg: Str of aggregation function, deafult = "last"
        str representing groupby object method, such as mean, var, last ...

    assert_frequency: bool, default = False
        resamples data to match freq, using foward fill method for
        missing values

    rolling_suffix: Str
        suffix for the rolling part of features names

    resample_suffix: Str
        suffix for the resample part of features names

    min_periods:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    center:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    win_type:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    on:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    axis:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    closed:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    rolling_operation_kwargs: dict
        key word arguments passed to rolling_operation

    resample_agg_kwargs: dict
        key word arguments passed to resample_agg
    '''

    if rolling_first:

        features_df = make_generic_rolling_features(
            df,
            calculate_columns = calculate_columns,
            group_columns = group_columns,
            date_column = date_column,
            suffix = rolling_suffix,
            rolling_operation = rolling_operation,
            window = window,
            min_periods=min_periods,
            center=center,
            win_type=win_type,
            on=on,
            axis=axis,
            closed=closed,
            **rolling_operation_kwargs
        )


        if extra_columns:

            features_df = features_df.merge(
                df[extra_columns + group_columns + [date_column]],
                how = 'left',
                left_on = group_columns + [date_column],
                right_on = group_columns + [date_column]
            )


        features_df = make_generic_resampling_and_shift_features(
            features_df,
            calculate_columns = None,
            date_column = date_column,
            group_columns = group_columns,
            freq = resample_freq,
            agg = resample_agg,
            assert_frequency = assert_frequency,
            suffix = resample_suffix,
            n_periods_shift = n_periods_shift,
        )

    else:

        features_df = make_generic_resampling_and_shift_features(
            df,
            calculate_columns = calculate_columns,
            date_column = date_column,
            group_columns = group_columns,
            freq = resample_freq,
            agg = resample_agg,
            assert_frequency = assert_frequency,
            suffix = resample_suffix,
            n_periods_shift = n_periods_shift,
        )


        features_df = features_df.merge(
            df[extra_columns + group_columns + [date_column]],
            how = 'left',
            left_on = group_columns + [date_column],
            right_on = group_columns + [date_column]
        )

        features_df = make_generic_rolling_features(
            features_df,
            calculate_columns = None,
            group_columns = group_columns,
            date_column = date_column,
            suffix = rolling_suffix,
            rolling_operation = rolling_operation,
            window = window,
            min_periods=min_periods,
            center=center,
            win_type=win_type,
            on=on,
            axis=axis,
            closed=closed,
            **rolling_operation_kwargs
        )



    return features_df


# Cell
from functools import reduce, partial
import os
import datetime as dt
from tqdm import tqdm
from warnings import warn

import pandas as pd
import numpy as np
import numba

from dask import dataframe as dd
from dask import delayed
from dask.diagnostics import ProgressBar


# Cell

def _get_index_rolling_windows(rolling_obj):
    '''
    get positional indexes of rows of each rolling window
    '''

    if hasattr(rolling_obj, '_selection'):
        previous_selection = getattr(rolling_obj, '_selection')
    else:
        previous_selection = None

    INDEX_LIST = []
    #define function to append values to global INDEX_LIST since rolling apply won't let return arrays
    def f(x): INDEX_LIST.append(x.astype(int)); return 0
    assert '__indexer__' not in rolling_obj.obj.columns, 'DataFrame should not contain any col with "__indexer__" name'
    rolling_obj.obj = rolling_obj.obj.assign(__indexer__ = np.arange(len(rolling_obj.obj)), inplace = True)
    rolling_obj._selection = '__indexer__'
    rolling_obj.apply(f, raw = True)
    rolling_obj.obj = rolling_obj.obj.drop(columns = ['__indexer__'])

    delattr(rolling_obj, '_selection')

    if not previous_selection is None:
        setattr(rolling_obj, '_selection', previous_selection)

    return INDEX_LIST


def _apply_custom_rolling(rolling_obj, func, raw = True, engine = 'numpy', *args, **kwargs):

    engines = {
        'numpy':_rolling_apply_custom_agg_numpy,
        'pandas':_rolling_apply_custom_agg_pandas,
        'numba':_rolling_apply_custom_agg_numpy_jit
    }
    _rolling_apply = engines[engine]

    indexes = _get_index_rolling_windows(rolling_obj)
    if hasattr(rolling_obj, '_selection'):
        if getattr(rolling_obj, '_selection') is None:
            values = _rolling_apply(rolling_obj.obj, indexes, func, *args, **kwargs)

        values = _rolling_apply(rolling_obj.obj[rolling_obj._selection], indexes, func, *args, **kwargs)
    else:
        values = _rolling_apply(rolling_obj.obj, indexes, func, *args, **kwargs)

    return values



def _rolling_apply_custom_agg_numpy_jit(df, indexes, func):
    '''
    applies some aggregation function over groups defined by index.
    groups are numpy arrays
    '''

    dfv = df.values
    # template of output to create empty array
    #use this for jit version
    shape = np.array(func(dfv[:1])).shape
    #d = [np.empty(*shape) for _ in  range(len(indexes))]
    result_array = np.empty((len(indexes),*shape))

    @numba.jit(forceobj=True)
    def _roll_apply(dfv, indexes, func, result_array):
        for i in np.arange(len(indexes)):
            data = dfv[indexes[i]]
            if len(data) > 0:
                result = func(data)
                result_array[i] = result
            else:
                result = np.empty(shape)


        return result_array

    return _roll_apply(dfv, indexes, func, result_array)


def _rolling_apply_custom_agg_numpy(df, indexes, func, *args, **kwargs):
    '''
    applies some aggregation function over groups defined by index.
    groups are numpy arrays
    '''

    dfv = df.values
    d = [[] for _ in range(len(indexes))]
    for i in tqdm(range(len(indexes))):
        data = dfv[indexes[i]]
        if len(data) > 0:
            result = func(data, *args, **kwargs)
            d[i] = result

    return d

def _rolling_apply_custom_agg_pandas(df, indexes, func, *args, **kwargs):
    '''
    applies some aggregation function over groups defined by index.
    groups are pandas dataframes
    '''

    # template of output to create empty array
    d = [[] for _ in range(len(indexes))]

    for i in tqdm(range(len(indexes))):
        data = df.iloc[indexes[i]]
        if len(data) > 0:
            result = func(data, *args, **kwargs)
            d[i] = result

    return pd.concat(d)

# Cell
def _make_rolling_groupby_object(df, group_columns, date_column):
    '''
    helping function to make computational graph creation faster
    '''
    groupby_object = df.set_index(date_column).groupby(group_columns)

    return groupby_object

def make_generic_rolling_features(
    df,
    calculate_columns,
    group_columns,
    date_column,
    suffix = None,
    rolling_operation = 'mean',
    window = '60D',
    min_periods=None,
    center=False,
    win_type=None,
    on=None,
    axis=0,
    closed=None,
    **rolling_operation_kwargs
):
    '''
    make generic/custom rolling opeartion for a given column, grouped by customer, having Data de Emissao as date index
    if calculate cols is None, than use all cols

    Parameters
    ----------

    df: DataFrame
        DataFrame to make rolling features over

    calculate_columns: list of str
        list of columns to perform rolling_operation over

    group_columns: list of str
        list of columns passed to GroupBy operator prior to rolling

    date_column: str
        datetime column to roll over

    suffix: Str
        suffix for features names

    rolling_operation: Str of aggregation function, deafult = "mean"
        str representing groupby object method, such as mean, var, quantile ...

    window:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    min_periods:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    center:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    win_type:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    on:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    axis:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    closed:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    rolling_operation_kwargs:
        key word arguments passed to rolling_operation

    Returns
    -------
    DataFrame with the new calculated features
    '''

    assert group_columns.__class__ in (set, tuple, list), 'group_columns type should be one of (tuple, list, set), not {group_columns.__class__}'
    if calculate_columns is None:
        calculate_columns = [i for i in df.columns if not i in [*group_columns, date_column]]

    keep_columns = [*group_columns, date_column, *calculate_columns]

    if not isinstance(df,(
        dd.groupby.DataFrameGroupBy,
        pd.core.groupby.generic.DataFrameGroupBy,
        pd.core.groupby.generic.SeriesGroupBy,
        dd.groupby.SeriesGroupBy
    )):

        df = _make_rolling_groupby_object(df, group_columns, date_column)

    if isinstance(df, (pd.core.groupby.generic.DataFrameGroupBy, pd.core.groupby.generic.SeriesGroupBy)):


        df = getattr(
            df[calculate_columns]
            .rolling(
                window = window,
                min_periods=min_periods,
                center=center,
                win_type=win_type,
                on=on,
                axis=axis,
                closed=closed
            ),
            rolling_operation,

        )(**rolling_operation_kwargs).reset_index()

    else: #syntax for dask groupby rolling

        df = df[calculate_columns].apply(
                lambda x: getattr(
                    x.sort_index().rolling(
                        window = window,
                        min_periods=min_periods,
                        center=center,
                        win_type=win_type,
                        on=on,
                        axis=axis,
                        closed=closed
                    ),
                    rolling_operation,
                )(**rolling_operation_kwargs).reset_index()
            #meta = meta, #works only for float rolling

            ).reset_index().drop(columns = [f'level_{len(group_columns)}']) #drop unwanted "level_n" cols


    if not suffix:

        df.columns = [
            f'{col}__rolling_{rolling_operation}_{window}_{str(rolling_operation_kwargs)}'
            if not col in (*group_columns, date_column) else col
            for col in df.columns
        ]
    else:
        df.columns = [
            f'{col}__rolling_{window}_{suffix}'
            if not col in (*group_columns, date_column) else col
            for col in df.columns
        ]

    return df

def _make_shift_resample_groupby_object(df, group_columns, date_column,freq, n_periods_shift):

    groupby_object = (
            df
            .assign(**{date_column:df[date_column] + pd.Timedelta(n_periods_shift,freq)}) #shift
            .set_index(date_column)
            .groupby([*group_columns, pd.Grouper(freq = freq)])
        )
    return groupby_object

def make_generic_resampling_and_shift_features(
    df, calculate_columns, group_columns, date_column, freq = 'm',
    agg = 'last', n_periods_shift = 0, assert_frequency = False, suffix = '',**agg_kwargs
):

    '''
    makes generic resamples (aggregates by time frequency) on column.
    shifts one period up to avoid information leakage.
    Doing this through this function, although imposing some limitations to resampling periods, is much more efficient than
    pandas datetime-set_index + groupby + resampling.

    Parameters
    ----------

    df: DataFrame
        DataFrame to make rolling features over

    calculate_columns: list of str
        list of columns to perform rolling_operation over

    group_columns: list of str
        list of columns passed to GroupBy operator prior to rolling

    date_column: str
        datetime column to roll over

    freq: valid pandas freq str:
        frequency to resample data

    agg: Str of aggregation function, deafult = "last"
        str representing groupby object method, such as mean, var, last ...

    n_periods_shift: int
        number of periods to perform the shift opeartion. shifting is important after aggregation to avoid information leakage
        e.g. assuming you have the information of the end of the month in the beggining of the month.

    assert_frequency: bool, default = False
        resamples data to match freq, using foward fill method for
        missing values

    suffix: Str
        suffix for features names

    agg_kwargs:
        key word arguments passed to agg

    Returns
    -------
    DataFrame with the new calculated features
    '''

    if calculate_columns is None:
        calculate_columns = [i for i in df.columns if not i in [*group_columns, date_column]]

    keep_columns = [*group_columns, date_column, *calculate_columns]

    df = (
        df
        .assign(**{date_column:df[date_column] + pd.Timedelta(n_periods_shift,freq)}) #shift
        .set_index(date_column)
        .groupby([*group_columns, pd.Grouper(freq = freq)])
    )


    if isinstance(agg, str):
        df = getattr(df[calculate_columns], agg)(**agg_kwargs)
    else:
        df = df[calculate_columns].apply(lambda x: agg(x,**agg_kwargs))


    if not suffix:
        df.columns = [f'{i}__{str(agg)}_{str(agg_kwargs)}' for i in df.columns]
    else:
        df.columns = [f'{i}__{suffix}' for i in df.columns]

    #create new shifted date_col
    #df.loc[:, date_column] = date_col_values


    if assert_frequency:
        df = df.reset_index()
        df = df.set_index(date_column).groupby(group_columns).resample(freq).fillna(method = 'ffill')


    resetable_indexes = list(set(df.index.names) - set(df.columns))
    df = df.reset_index(level = resetable_indexes)
    df = df.reset_index(drop = True)

    return df


def create_rolling_resampled_features(
    df,
    calculate_columns,
    group_columns,
    date_column,
    extra_columns = [],
    n_periods_shift = 1,
    rolling_first = True,
    rolling_operation = 'mean',
    window = '60D',
    resample_freq = 'm',
    resample_agg = 'last',
    assert_frequency = False,
    rolling_suffix = '',
    resample_suffix = '',
    min_periods=None,
    center=False,
    win_type=None,
    on=None,
    axis=0,
    closed=None,
    rolling_operation_kwargs = {},
    resample_agg_kwargs = {}
):
    '''
    calculates rolling features groupwise, than resamples according to resample period.
    calculations can be done the other way arround if rolling_first is set to False

    Parameters
    ----------


    df: DataFrame
        DataFrame to make rolling features over

    calculate_columns: list of str
        list of columns to perform rolling_operation over

    group_columns: list of str
        list of columns passed to GroupBy operator prior to rolling

    date_column: str
        datetime column to roll over

    extra_columns: list of str
        list of extra columns to be passed to the final dataframe without aggregation (takes the last values, assumes they're constant along groupby).
        usefull to pass merge keys

    n_periods_shift: int
        number of periods to perform the shift opeartion. shifting is important after aggregation to avoid information leakage
        e.g. assuming you have the information of the end of the month in the beggining of the month.

    rolling_first: bool, deafult = True
        whether to perform rolling before resampling, or the other way arround

    rolling_operation: Str of aggregation function, deafult = "mean"
        str representing groupby object method, such as mean, var, quantile ...

    window:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    resample_freq: valid pandas freq str:
        frequency to resample data

    resample_agg: Str of aggregation function, deafult = "last"
        str representing groupby object method, such as mean, var, last ...

    assert_frequency: bool, default = False
        resamples data to match freq, using foward fill method for
        missing values

    rolling_suffix: Str
        suffix for the rolling part of features names

    resample_suffix: Str
        suffix for the resample part of features names

    min_periods:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    center:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    win_type:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    on:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    axis:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    closed:
        DataFrameGroupBy.Rolling parameter. please refer to documentation

    rolling_operation_kwargs: dict
        key word arguments passed to rolling_operation

    resample_agg_kwargs: dict
        key word arguments passed to resample_agg
    '''

    if rolling_first:

        features_df = make_generic_rolling_features(
            df,
            calculate_columns = calculate_columns,
            group_columns = group_columns,
            date_column = date_column,
            suffix = rolling_suffix,
            rolling_operation = rolling_operation,
            window = window,
            min_periods=min_periods,
            center=center,
            win_type=win_type,
            on=on,
            axis=axis,
            closed=closed,
            **rolling_operation_kwargs
        )


        if extra_columns:

            features_df = features_df.merge(
                df[extra_columns + group_columns + [date_column]],
                how = 'left',
                left_on = group_columns + [date_column],
                right_on = group_columns + [date_column]
            )


        features_df = make_generic_resampling_and_shift_features(
            features_df,
            calculate_columns = None,
            date_column = date_column,
            group_columns = group_columns,
            freq = resample_freq,
            agg = resample_agg,
            assert_frequency = assert_frequency,
            suffix = resample_suffix,
            n_periods_shift = n_periods_shift,
        )

    else:

        features_df = make_generic_resampling_and_shift_features(
            df,
            calculate_columns = calculate_columns,
            date_column = date_column,
            group_columns = group_columns,
            freq = resample_freq,
            agg = resample_agg,
            assert_frequency = assert_frequency,
            suffix = resample_suffix,
            n_periods_shift = n_periods_shift,
        )


        features_df = features_df.merge(
            df[extra_columns + group_columns + [date_column]],
            how = 'left',
            left_on = group_columns + [date_column],
            right_on = group_columns + [date_column]
        )

        features_df = make_generic_rolling_features(
            features_df,
            calculate_columns = None,
            group_columns = group_columns,
            date_column = date_column,
            suffix = rolling_suffix,
            rolling_operation = rolling_operation,
            window = window,
            min_periods=min_periods,
            center=center,
            win_type=win_type,
            on=on,
            axis=axis,
            closed=closed,
            **rolling_operation_kwargs
        )



    return features_df
