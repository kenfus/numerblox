# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/05_postprocessing.ipynb (unless otherwise specified).

__all__ = ['BasePostProcessor', 'Standardizer', 'MeanEnsembler', 'DonateWeightedEnsembler', 'GeometricMeanEnsembler',
           'FeatureNeutralizer', 'FeaturePenalizer', 'AwesomePostProcessor']

# Cell
import scipy
import numpy as np
import pandas as pd
import tensorflow as tf
from typing import Union
import scipy.stats as sp
from tqdm.auto import tqdm
from typeguard import typechecked
from rich import print as rich_print
from scipy.stats.mstats import gmean
from sklearn.preprocessing import MinMaxScaler

from .numerframe import NumerFrame, create_numerframe
from .preprocessing import BaseProcessor, display_processor_info

# Cell
class BasePostProcessor(BaseProcessor):
    """
    Base class for postprocessing objects.
    Postprocessors manipulate or ensemble prediction column(s)
    and add them to a Dataset.
    """
    def __init__(self, final_col_name: str):
        super().__init__()
        self.final_col_name = final_col_name
        assert final_col_name.startswith("prediction"), f"final_col name should start with 'prediction'. Got {final_col_name}"

    def transform(self, dataset: Union[pd.DataFrame, NumerFrame], *args, **kwargs) -> NumerFrame:
        ...

# Cell
@typechecked
class Standardizer(BaseProcessor):
    """
    Uniform standardization of prediction columns.
    All values should only contain values in the range [0...1].
    """
    def __init__(self, cols: list = None):
        super().__init__()
        self.cols = cols

    @display_processor_info
    def transform(self, dataf: NumerFrame) -> NumerFrame:
        cols = dataf.prediction_cols if not self.cols else self.cols
        for col in cols:
            assert dataf[col].between(0, 1).all(), f"All values should only contain values between 0 and 1. Does not hold for '{col}'"
        dataf.loc[:, cols] = dataf.groupby(dataf.meta.era_col)[cols].rank(pct=True)
        return NumerFrame(dataf)

# Cell
@typechecked
class MeanEnsembler(BasePostProcessor):
    """ Take simple mean of multiple cols and store in new col. """
    def __init__(self, cols: list, final_col_name: str):
        super().__init__(final_col_name=final_col_name)
        self.cols = cols

    @display_processor_info
    def transform(self, dataf: Union[pd.DataFrame, NumerFrame]) -> NumerFrame:
        dataf.loc[:, self.final_col_name] = dataf.loc[:, self.cols].mean(axis=1)
        rich_print(f":stew: Ensembled [blue]'{self.cols}'[blue] with simple mean and saved in [bold]'{self.final_col_name}'[bold] :stew:")
        return NumerFrame(dataf)

# Cell
@typechecked
class DonateWeightedEnsembler(BasePostProcessor):
    """
    Weighted average as per Donate et al.'s formula
    https://doi.org/10.1016/j.neucom.2012.02.053
    [0.0625, 0.0625, 0.125, 0.25, 0.5] for 5 fold
    Source: https://www.kaggle.com/gogo827jz/jane-street-supervised-autoencoder-mlp
    """
    def __init__(self, cols: list, final_col_name: str):
        super().__init__(final_col_name=final_col_name)
        self.cols = cols
        self.n_cols = len(cols)
        self.weights = self._get_weights()

    @display_processor_info
    def transform(self, dataf: Union[pd.DataFrame, NumerFrame]) -> NumerFrame:
        dataf.loc[:, self.final_col_name] = np.average(dataf.loc[:, self.cols],
                                                       weights=self.weights, axis=1)
        rich_print(f":stew: Ensembled [blue]'{self.cols}'[/blue] with [bold]{self.__class__.__name__}[/bold] and saved in [bold]'{self.final_col_name}'[bold] :stew:")
        return NumerFrame(dataf)

    def _get_weights(self) -> list:
        weights = []
        for j in range(1, self.n_cols+1):
            j = 2 if j == 1 else j
            weights.append(1 / (2**(self.n_cols + 1 - j)))
        return weights

# Cell
@typechecked
class GeometricMeanEnsembler(BasePostProcessor):
    """
    Calculate the weighted Geometric mean using inverse correlation.
    """
    def __init__(self, cols: list, final_col_name: str):
        super().__init__(final_col_name=final_col_name)
        self.cols = cols
        self.n_cols = len(cols)

    @display_processor_info
    def transform(self, dataf: Union[pd.DataFrame, NumerFrame], *args, **kwargs) -> NumerFrame:
        new_col = dataf.loc[:, self.cols].apply(gmean, axis=1)
        dataf.loc[:, self.final_col_name] = new_col
        rich_print(f":stew: Ensembled [blue]'{self.cols}'[/blue] with [bold]{self.__class__.__name__}[/bold] and saved in [bold]'{self.final_col_name}'[bold] :stew:")
        return NumerFrame(dataf)

# Cell
@typechecked
class FeatureNeutralizer(BasePostProcessor):
    """
    Classic feature neutralization
    Subtracting Linear model.
    :param feature_names: List of column names to neutralize against.
    :param pred_name: Prediction column to neutralize.
    :param era_col: Numerai era column
    :param proportion: Number in range [0...1] indication how much to neutralize.
    """
    def __init__(self,
                 feature_names: list = None,
                 pred_name: str = "prediction",
                 era_col: str = "era",
                 proportion: float = 0.5):
        self.pred_name = pred_name
        self.proportion = proportion
        assert 0. <= proportion <= 1., f"'proportion' should be a float in range [0...1]. Got '{proportion}'."
        self.new_col_name = f"{self.pred_name}_neutralized_{self.proportion}"
        super().__init__(final_col_name=self.new_col_name)

        self.feature_names = feature_names
        self.era_col = era_col

    @display_processor_info
    def transform(self, dataf: NumerFrame) -> NumerFrame:
        feature_names = self.feature_names if self.feature_names else dataf.feature_cols
        neutralized_preds = dataf.groupby(self.era_col)\
            .apply(lambda x: self.normalize_and_neutralize(x, [self.pred_name], feature_names))
        dataf.loc[:, self.new_col_name] = MinMaxScaler().fit_transform(neutralized_preds)
        rich_print(f":robot: Neutralized [bold blue]'{self.pred_name}'[bold blue] with proportion [bold]'{self.proportion}'[/bold] :robot:")
        rich_print(f"New neutralized column = [bold green]'{self.new_col_name}'[/bold green].")
        return NumerFrame(dataf)

    def neutralize(self, dataf: pd.DataFrame, columns: list, by: list) -> pd.DataFrame:
        scores = dataf[columns]
        exposures = dataf[by].values
        scores = scores - self.proportion * exposures.dot(np.linalg.pinv(exposures).dot(scores))
        return scores / scores.std()

    @staticmethod
    def normalize(dataf: pd.DataFrame) -> np.ndarray:
        normalized_ranks = (dataf.rank(method="first") - 0.5) / len(dataf)
        return sp.norm.ppf(normalized_ranks)

    def normalize_and_neutralize(self, dataf: pd.DataFrame, columns: list, by: list) -> pd.DataFrame:
        # Convert the scores to a normal distribution
        dataf[columns] = self.normalize(dataf[columns])
        dataf[columns] = self.neutralize(dataf, columns, by)
        return dataf[columns]

# Cell
@typechecked
class FeaturePenalizer(BasePostProcessor):
    """ Feature penalization with Tensorflow. """
    def __init__(self, model_list: list, max_exposure: float,
                 risky_feature_names: list = None, pred_name: str = "prediction", era_col: str = 'era'):
        self.pred_name = pred_name
        self.max_exposure = max_exposure
        assert 0. <= max_exposure <= 1., f"'max_exposure' should be a float in range [0...1]. Got '{max_exposure}'."
        self.new_col_name = f"{self.pred_name}_penalized_{self.max_exposure}"
        super().__init__(final_col_name=self.new_col_name)

        self.model_list = model_list
        self.risky_feature_names = risky_feature_names
        self.era_col = era_col

    @display_processor_info
    def transform(self, dataf: Union[pd.DataFrame, NumerFrame]) -> NumerFrame:
        risky_feature_names = dataf.feature_cols if not self.risky_feature_names else self.risky_feature_names
        for model_name in tqdm(self.model_list, desc="Feature Penalization"):
            penalized_data = self.reduce_all_exposures(
                            df=dataf,
                            column=self.pred_name,
                            neutralizers=risky_feature_names,
                        )
            new_pred_col = f"prediction_{self.pred_name}_{model_name}_FP_{self.max_exposure}"
            dataf.loc[:, new_pred_col] = penalized_data[self.pred_name]
        return NumerFrame(dataf)

    def reduce_all_exposures(self, df: pd.DataFrame,
                             column: str = "prediction",
                             neutralizers: list = None,
                             normalize=True,
                             gaussianize=True,
                             ):
        if neutralizers is None:
            neutralizers = [x for x in df.columns if x.startswith("feature")]
        neutralized = []

        for era in tqdm(df[self.era_col].unique()):
            df_era = df[df[self.era_col] == era]
            scores = df_era[[column]].values
            exposure_values = df_era[neutralizers].values

            if normalize:
                scores2 = []
                for x in scores.T:
                    x = (scipy.stats.rankdata(x, method='ordinal') - .5) / len(x)
                    if gaussianize:
                        x = scipy.stats.norm.ppf(x)
                    scores2.append(x)
                scores = np.array(scores2)[0]

            scores, weights = self._reduce_exposure(scores, exposure_values,
                                                    len(neutralizers), None)

            scores /= tf.math.reduce_std(scores)
            scores -= tf.reduce_min(scores)
            scores /= tf.reduce_max(scores)
            neutralized.append(scores.numpy())

        predictions = pd.DataFrame(np.concatenate(neutralized),
                                   columns=[column], index=df.index)
        return predictions

    def _reduce_exposure(self, prediction, features, input_size=50, weights=None):
        model = tf.keras.models.Sequential([
            tf.keras.layers.Input(input_size),
            tf.keras.experimental.LinearModel(use_bias=False),
        ])
        feats = tf.convert_to_tensor(features - 0.5, dtype=tf.float32)
        pred = tf.convert_to_tensor(prediction, dtype=tf.float32)
        if weights is None:
            optimizer = tf.keras.optimizers.Adamax()
            start_exp = self.__exposures(feats, pred[:, None])
            target_exps = tf.clip_by_value(start_exp, -self.max_exposure, self.max_exposure)
            self._train_loop(model, optimizer, feats, pred, target_exps)
        else:
            model.set_weights(weights)
        return pred[:,None] - model(feats), model.get_weights()


    def _train_loop(self, model, optimizer, feats, pred, target_exps):
        for i in range(1000000):
            loss, grads = self.__train_loop_body(model, feats, pred, target_exps)
            optimizer.apply_gradients(zip(grads, model.trainable_variables))
            if loss < 1e-7:
                break

    @tf.function(experimental_relax_shapes=True)
    def __train_loop_body(self, model, feats, pred, target_exps):
        with tf.GradientTape() as tape:
            exps = self.__exposures(feats, pred[:, None] - model(feats, training=True))
            loss = tf.reduce_sum(tf.nn.relu(tf.nn.relu(exps) - tf.nn.relu(target_exps)) +
                                 tf.nn.relu(tf.nn.relu(-exps) - tf.nn.relu(-target_exps)))
        return loss, tape.gradient(loss, model.trainable_variables)

    @staticmethod
    @tf.function(experimental_relax_shapes=True, experimental_compile=True)
    def __exposures(x, y):
        x = x - tf.math.reduce_mean(x, axis=0)
        x = x / tf.norm(x, axis=0)
        y = y - tf.math.reduce_mean(y, axis=0)
        y = y / tf.norm(y, axis=0)
        return tf.matmul(x, y, transpose_a=True)

# Cell
@typechecked
class AwesomePostProcessor(BasePostProcessor):
    """
    - TEMPLATE -
    Do some awesome postprocessing.
    :param final_col_name: Column name to store manipulated or ensembled predictions in.
    """
    def __init__(self, final_col_name: str, *args, **kwargs):
        super().__init__(final_col_name=final_col_name)

    @display_processor_info
    def transform(self, dataf: Union[pd.DataFrame, NumerFrame], *args, **kwargs) -> NumerFrame:
        # Do processing
        ...
        # Add new column(s) for manipulated data (optional)
        dataf.loc[:, self.final_col_name] = ...
        ...
        # Parse all contents to the next pipeline step
        return NumerFrame(dataf)