# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/03_preprocessing.ipynb (unless otherwise specified).

__all__ = ['BaseProcessor', 'support_dataset_processing', 'display_processor_info', 'CopyPreProcessor',
           'FeatureSelectionPreProcessor', 'GroupStatsPreProcessor', 'TalibPatternFeatures', 'TalibVolumeFeatures',
           'RealizedVolFeatures', 'QuarticityFeatures', 'AwesomePreProcessor']

# Cell
import uuid
import time
import talib
import numpy as np
import pandas as pd
import datetime as dt
from typing import Union
from functools import wraps
from scipy.special import gamma
from typeguard import typechecked
from abc import ABC, abstractmethod
from rich import print as rich_print

from .dataset import Dataset, create_dataset

# Cell
class BaseProcessor(ABC):
    """
    New Preprocessors and Postprocessors should inherit from this object
    and implement the transform method.
    """
    def __init__(self):
        ...

    @abstractmethod
    def transform(self, dataset: Dataset, *args, **kwargs) -> Dataset:
        ...

    def __call__(self, dataset: Dataset, *args, **kwargs) -> Dataset:
        return self.transform(dataset=dataset, *args, **kwargs)

# Cell
def support_dataset_processing(func):
    """
    Make existing DataFrame transformer compatible with Dataset input.
    :param func: Some function/method that takes Pandas DataFrame as input
    and return Pandas DataFrame.
    """
    @wraps(func)
    def wrapper(dataset: Dataset, *args, **kwargs) -> Dataset:
        dataf_transform = func(dataset.dataf, *args, **kwargs)
        metadata = dataset.__dict__
        metadata.pop("dataf", None)
        return Dataset(dataf_transform, metadata)
    return wrapper

# Cell
def display_processor_info(func):
    """ Fancy console output for data processing. """
    @wraps(func)
    def wrapper(*args, **kwargs):
        tic = dt.datetime.now()
        result = func(*args, **kwargs)
        time_taken = str(dt.datetime.now() - tic)
        class_name = func.__qualname__.split('.')[0]
        rich_print(f":white_check_mark: Finished step [bold]{class_name}[/bold]. Output shape={result.dataf.shape}. Time taken for step: [blue]{time_taken}[/blue]. :white_check_mark:")
        return result
    return wrapper

# Cell
@typechecked
class CopyPreProcessor(BaseProcessor):
    """Copy DataFrame to avoid manipulation of original DataFrame. """
    def __init__(self):
        super(CopyPreProcessor, self).__init__()

    @display_processor_info
    def transform(self, dataset: Dataset, *args, **kwargs) -> Dataset:
        return dataset.copy_dataset()

# Cell
@typechecked
class FeatureSelectionPreProcessor(BaseProcessor):
    """
    Keep only features given + all target, predictions and aux columns.
    """
    def __init__(self, feature_cols: Union[str, list]):
        super(FeatureSelectionPreProcessor, self).__init__()
        self.feature_cols = feature_cols

    @display_processor_info
    def transform(self, dataset: Dataset) -> Dataset:
        keep_cols = self.feature_cols + dataset.target_cols + dataset.prediction_cols + dataset.aux_cols
        dataset.dataf = dataset.dataf.loc[:, keep_cols]
        return Dataset(**dataset.__dict__)

# Cell
@typechecked
class GroupStatsPreProcessor(BaseProcessor):
    """
    WARNING: Only supported for Version 1 (legacy) data.
    Calculate group statistics for all data groups.
    """
    def __init__(self):
        super(GroupStatsPreProcessor, self).__init__()
        self.group_names = ["intelligence", "wisdom", "charisma",
                            "dexterity", "strength", "constitution"]

    @display_processor_info
    def transform(self, dataset: Dataset, *args, **kwargs) -> Dataset:
        self._check_data_validity(dataset=dataset)
        dataset.dataf = dataset.dataf.pipe(self._add_group_features)
        return Dataset(**dataset.__dict__)

    def _add_group_features(self, dataf: pd.DataFrame) -> pd.DataFrame:
        """ Mean, standard deviation and skew for each group. """
        for group in self.group_names:
            cols = [col for col in dataf.columns if group in col]
            dataf[f"feature_{group}_mean"] = dataf[cols].mean(axis=1)
            dataf[f"feature_{group}_std"] = dataf[cols].std(axis=1)
            dataf[f"feature_{group}_skew"] = dataf[cols].skew(axis=1)
        return dataf

    def _check_data_validity(self, dataset: Dataset):
        assert hasattr(dataset, 'version'), f"Version should be specified for '{self.__class__.__name__}' This Preprocessor will only work on version 1 data."
        assert getattr(dataset, 'version') == 1, f"'{self.__class__.__name__}' only works on version 1 data. Got version: '{getattr(dataset, 'version')}'."

# Cell
@typechecked
class TalibPatternFeatures(BaseProcessor):
    """
    Get all pattern recognition features available in TA-Lib
    More information: https://mrjbq7.github.io/ta-lib/func_groups/pattern_recognition.html
    """
    def __init__(self, ticker_col: str = "ticker"):
        super(TalibPatternFeatures, self).__init__()
        self.ticker_col = ticker_col
        # All pattern recognition features start with "CDL" in TA-Lib
        self.funcs = [getattr(talib, name) for name in dir(talib) if name.startswith("CDL")]

    @display_processor_info
    def transform(self, dataset: Dataset, *args, **kwargs) -> Dataset:
        all_tickers = list(dataset.dataf[self.ticker_col].unique())
        for func in self.funcs:
            for ticker in all_tickers:
                index_mask = dataset.dataf[self.ticker_col] == ticker
                sub_df = dataset.dataf.loc[index_mask, :]
                open, high = sub_df['Open'], sub_df['High']
                low, close = sub_df['Low'], sub_df['Close']
                dataset.dataf.loc[index_mask, f"feature_{func.__qualname__}"] = func(open, high, low, close)
        return Dataset(**dataset.__dict__)

# Cell
@typechecked
class TalibVolumeFeatures(BaseProcessor):
    """
    Get all volume features using TA-Lib
    More information: https://mrjbq7.github.io/ta-lib/func_groups/volume_indicators.html

    :param ticker_col: Column name that points to ticker names
    :param fastperiod, slowperiod: Periodic arguments for ADOSC (Chaikin A/D Oscillator).
    See http://www.tadoc.org/indicator/ADOSC.htm for more information on how these arguments are used.
    """
    def __init__(self, ticker_col: str = "ticker", fastperiod: int = 3, slowperiod: int = 10):
        super(TalibVolumeFeatures, self).__init__()
        self.ticker_col = ticker_col
        self.volume_features = ['AD', 'ADOSC', 'OBV']
        self.fastperiod = fastperiod
        self.slowperiod = slowperiod

    @display_processor_info
    def transform(self, dataset: Dataset) -> Dataset:
        all_tickers = list(dataset.dataf[self.ticker_col].unique())
        for ticker in all_tickers:
            index_mask = dataset.dataf[self.ticker_col] == ticker
            sub_df = dataset.dataf.loc[index_mask, :]

            high, low = sub_df['High'].to_numpy(), sub_df['Low'].to_numpy()
            close, volume = sub_df['Close'].to_numpy(), sub_df['Volume'].to_numpy()

            dataset.dataf.loc[index_mask, "feature_AD"] = talib.AD(high, low, close, volume)
            adosc = talib.ADOSC(high, low, close, volume, fastperiod=self.fastperiod, slowperiod=self.slowperiod)
            dataset.dataf.loc[index_mask, "feature_ADOSC"] = np.nan_to_num(adosc, nan=0.0)
            dataset.dataf.loc[index_mask, "feature_OBV"] = talib.OBV(close, volume)
        return Dataset(**dataset.__dict__)

# Cell
@typechecked
class RealizedVolFeatures(BaseProcessor):
    """
    Features based on realized volatility features.
    Dataset DataFrame should have a column named "Close".
    Source and more information: https://dspyt.com/advanced-realized-volatility-and-quarticity/
    """
    def __init__(self, ticker_col: str = 'ticker', price_col: str = 'Close'):
        super(RealizedVolFeatures, self).__init__()
        self.ticker_col = ticker_col
        self.price_col = price_col

    @display_processor_info
    def transform(self, dataset: Dataset, *args, **kwargs) -> Dataset:
        """ Get all realized volatility features. """
        series = dataset.dataf.loc[:, self.price_col]
        tickers = dataset.dataf.loc[:, self.ticker_col]
        dataset.dataf.loc[:, "feature_vol2"] = series.groupby(tickers).agg(self.realized_2)
        dataset.dataf.loc[:, "feature_vol3"] = series.groupby(tickers).agg(self.realized_3)
        dataset.dataf.loc[:, "feature_vol4"] = series.groupby(tickers).agg(self.realized_4)
        # Parse all contents of Dataset to the next pipeline step
        return Dataset(**dataset.__dict__)

    @staticmethod
    def simple_realized_vol(series: pd.Series) -> np.float64:
        """ Most simple way to calculate realized volatility. """
        return np.sqrt(np.sum(series**2))

    @staticmethod
    def realized_2(series: pd.Series) -> np.float64:
        return np.sqrt(np.sum(series**4)/(6*np.sum(series**2)))

    @staticmethod
    def realized_3(series: pd.Series) -> np.float64:
        return np.sqrt(((np.pi**2)*np.sum(abs(series.rolling(window=4).apply(np.product,
                                                                             raw=True))))/(8*np.sum(series**2)))

    @staticmethod
    def realized_4(series: pd.Series) -> np.float64:
        numerator = (gamma(1/2)**3)*np.sum((abs(series)**(4/3)).rolling(window=3).apply(np.prod))
        denominator = 8 * (gamma(7/6)**3)*np.sum(series**2)
        return np.sqrt(numerator/denominator)

# Cell
@typechecked
class QuarticityFeatures(BaseProcessor):
    """
    Quarticity (Vol of vol) features.
    Source and more information: https://dspyt.com/advanced-realized-volatility-and-quarticity/
    """
    def __init__(self, ticker_col: str = 'ticker', price_col: str = 'Close'):
        super(QuarticityFeatures, self).__init__()
        self.ticker_col = ticker_col
        self.price_col = price_col

    @display_processor_info
    def transform(self, dataset: Dataset, *args, **kwargs) -> Dataset:
        """ Get most powerful quarticity features for every stock. """
        series = dataset.dataf.loc[:, self.price_col]
        tickers = dataset.dataf.loc[:, self.ticker_col]
        quad_quarticity = series.groupby(tickers).agg(self.realized_quadpower_quarticity)
        tripower_quarticity = series.groupby(tickers).agg(self.realized_tripower_quarticity)
        dataset.dataf.loc[:, "feature_quadpower_quarticity"] = quad_quarticity
        dataset.dataf.loc[:, "feature_tripower_quarticity"] = tripower_quarticity
        return Dataset(**dataset.__dict__)

    @staticmethod
    def realized_quarticity(series: pd.Series) -> np.float64:
        """
        The realized fourth-power variation or realized quarticity
        is a consistent estimator of the integrated quarticity.
        """
        return np.sum(series**4) * series.shape[0] / 3

    @staticmethod
    def realized_quadpower_quarticity(series: pd.Series) -> np.float64:
        """
        A more robust estimator compared to realized quarticity,
        particularly in the presence of jumps, is the realized quad-power quarticity.
        """
        series = abs(series.rolling(window=4).apply(np.product, raw=True))
        return (np.sum(series) * series.shape[0] * (np.pi**2)) / 4

    @staticmethod
    def realized_tripower_quarticity(series: pd.Series) -> np.float64:
        """ Similarly robust estimator to quad power quarticity. """
        series = series ** (4/3)
        series = abs(series).rolling(window=3).apply(np.prod, raw=True)
        return series.shape[0]*0.25*((gamma(1/2)**3)/(gamma(7/6)**3))*np.sum(series)

# Cell
class AwesomePreProcessor(BaseProcessor):
    """
    - TEMPLATE -
    Do some awesome preprocessing.
    """
    def __init__(self, *args, **kwargs):
        super(AwesomePreProcessor, self).__init__()

    @display_processor_info
    def transform(self, dataset: Dataset, *args, **kwargs) -> Dataset:
        # Do processing
        ...
        # Parse all contents of Dataset to the next pipeline step
        return Dataset(**dataset.__dict__)