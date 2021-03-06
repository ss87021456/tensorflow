# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
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
# ==============================================================================
"""Tests for feature_column."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import copy

import numpy as np

from tensorflow.core.example import example_pb2
from tensorflow.core.example import feature_pb2
from tensorflow.python.client import session
from tensorflow.python.feature_column import feature_column as fc
from tensorflow.python.framework import constant_op
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import errors
from tensorflow.python.framework import ops
from tensorflow.python.framework import sparse_tensor
from tensorflow.python.ops import lookup_ops
from tensorflow.python.ops import parsing_ops
from tensorflow.python.ops import variable_scope
from tensorflow.python.ops import variables as variables_lib
from tensorflow.python.platform import test


def _initialized_session():
  sess = session.Session()
  sess.run(variables_lib.global_variables_initializer())
  sess.run(lookup_ops.tables_initializer())
  return sess


class LazyColumnTest(test.TestCase):

  def test_transormations_called_once(self):

    class TransformCounter(fc._FeatureColumn):

      def __init__(self):
        self.num_transform = 0

      @property
      def name(self):
        return 'TransformCounter'

      def _transform_feature(self, cache):
        self.num_transform += 1  # Count transform calls.
        return cache.get('a')

      @property
      def _parse_example_config(self):
        pass

    builder = fc._LazyBuilder(features={'a': [[2], [3.]]})
    column = TransformCounter()
    self.assertEqual(0, column.num_transform)
    builder.get(column)
    self.assertEqual(1, column.num_transform)
    builder.get(column)
    self.assertEqual(1, column.num_transform)

  def test_returns_transform_output(self):

    class Transformer(fc._FeatureColumn):

      @property
      def name(self):
        return 'Transformer'

      def _transform_feature(self, cache):
        return 'Output'

      @property
      def _parse_example_config(self):
        pass

    builder = fc._LazyBuilder(features={'a': [[2], [3.]]})
    column = Transformer()
    self.assertEqual('Output', builder.get(column))
    self.assertEqual('Output', builder.get(column))

  def test_does_not_pollute_given_features_dict(self):

    class Transformer(fc._FeatureColumn):

      @property
      def name(self):
        return 'Transformer'

      def _transform_feature(self, cache):
        return 'Output'

      @property
      def _parse_example_config(self):
        pass

    features = {'a': [[2], [3.]]}
    builder = fc._LazyBuilder(features=features)
    builder.get(Transformer())
    self.assertEqual(['a'], list(features.keys()))

  def test_error_if_feature_is_not_found(self):
    builder = fc._LazyBuilder(features={'a': [[2], [3.]]})
    with self.assertRaisesRegexp(ValueError,
                                 'bbb is not in features dictionary'):
      builder.get('bbb')

  def test_not_supported_feature_column(self):

    class NotAProperColumn(fc._FeatureColumn):

      @property
      def name(self):
        return 'NotAProperColumn'

      def _transform_feature(self, cache):
        # It should return not None.
        pass

      @property
      def _parse_example_config(self):
        pass

    builder = fc._LazyBuilder(features={'a': [[2], [3.]]})
    with self.assertRaisesRegexp(ValueError,
                                 'NotAProperColumn is not supported'):
      builder.get(NotAProperColumn())

  def test_key_should_be_string_or_feature_colum(self):

    class NotAFeatureColumn(object):
      pass

    builder = fc._LazyBuilder(features={'a': [[2], [3.]]})
    with self.assertRaisesRegexp(
        TypeError, '"key" must be either a "str" or "_FeatureColumn".'):
      builder.get(NotAFeatureColumn())


class NumericColumnTest(test.TestCase):

  def test_defaults(self):
    a = fc.numeric_column('aaa')
    self.assertEqual('aaa', a.key)
    self.assertEqual((1,), a.shape)
    self.assertIsNone(a.default_value)
    self.assertEqual(dtypes.float32, a.dtype)
    self.assertIsNone(a.normalizer_fn)

  def test_shape_saved_as_tuple(self):
    a = fc.numeric_column('aaa', shape=[1, 2], default_value=[[3, 2.]])
    self.assertEqual((1, 2), a.shape)

  def test_default_value_saved_as_tuple(self):
    a = fc.numeric_column('aaa', default_value=4.)
    self.assertEqual((4.,), a.default_value)
    a = fc.numeric_column('aaa', shape=[1, 2], default_value=[[3, 2.]])
    self.assertEqual(((3., 2.),), a.default_value)

  def test_shape_and_default_value_compatibility(self):
    fc.numeric_column('aaa', shape=[2], default_value=[1, 2.])
    with self.assertRaisesRegexp(ValueError, 'The shape of default_value'):
      fc.numeric_column('aaa', shape=[2], default_value=[1, 2, 3.])
    fc.numeric_column(
        'aaa', shape=[3, 2], default_value=[[2, 3], [1, 2], [2, 3.]])
    with self.assertRaisesRegexp(ValueError, 'The shape of default_value'):
      fc.numeric_column(
          'aaa', shape=[3, 1], default_value=[[2, 3], [1, 2], [2, 3.]])
    with self.assertRaisesRegexp(ValueError, 'The shape of default_value'):
      fc.numeric_column(
          'aaa', shape=[3, 3], default_value=[[2, 3], [1, 2], [2, 3.]])

  def test_default_value_type_check(self):
    fc.numeric_column(
        'aaa', shape=[2], default_value=[1, 2.], dtype=dtypes.float32)
    fc.numeric_column(
        'aaa', shape=[2], default_value=[1, 2], dtype=dtypes.int32)
    with self.assertRaisesRegexp(TypeError, 'must be compatible with dtype'):
      fc.numeric_column(
          'aaa', shape=[2], default_value=[1, 2.], dtype=dtypes.int32)
    with self.assertRaisesRegexp(TypeError,
                                 'default_value must be compatible with dtype'):
      fc.numeric_column('aaa', default_value=['string'])

  def test_shape_must_be_positive_integer(self):
    with self.assertRaisesRegexp(TypeError, 'shape dimensions must be integer'):
      fc.numeric_column(
          'aaa', shape=[
              1.0,
          ])

    with self.assertRaisesRegexp(ValueError,
                                 'shape dimensions must be greater than 0'):
      fc.numeric_column(
          'aaa', shape=[
              0,
          ])

  def test_dtype_is_convertable_to_float(self):
    with self.assertRaisesRegexp(ValueError,
                                 'dtype must be convertible to float'):
      fc.numeric_column('aaa', dtype=dtypes.string)

  def test_scalar_deafult_value_fills_the_shape(self):
    a = fc.numeric_column('aaa', shape=[2, 3], default_value=2.)
    self.assertEqual(((2., 2., 2.), (2., 2., 2.)), a.default_value)

  def test_parse_config(self):
    a = fc.numeric_column('aaa', shape=[2, 3], dtype=dtypes.int32)
    self.assertEqual({
        'aaa': parsing_ops.FixedLenFeature((2, 3), dtype=dtypes.int32)
    }, a._parse_example_config)

  def test_parse_example_no_default_value(self):
    price = fc.numeric_column('price', shape=[2])
    data = example_pb2.Example(features=feature_pb2.Features(
        feature={
            'price':
                feature_pb2.Feature(float_list=feature_pb2.FloatList(
                    value=[20., 110.]))
        }))
    features = parsing_ops.parse_example(
        serialized=[data.SerializeToString()],
        features=price._parse_example_config)
    self.assertIn('price', features)
    with self.test_session():
      self.assertAllEqual([[20., 110.]], features['price'].eval())

  def test_parse_example_with_default_value(self):
    price = fc.numeric_column('price', shape=[2], default_value=11.)
    data = example_pb2.Example(features=feature_pb2.Features(
        feature={
            'price':
                feature_pb2.Feature(float_list=feature_pb2.FloatList(
                    value=[20., 110.]))
        }))
    no_data = example_pb2.Example(features=feature_pb2.Features(
        feature={
            'something_else':
                feature_pb2.Feature(float_list=feature_pb2.FloatList(
                    value=[20., 110.]))
        }))
    features = parsing_ops.parse_example(
        serialized=[data.SerializeToString(),
                    no_data.SerializeToString()],
        features=price._parse_example_config)
    self.assertIn('price', features)
    with self.test_session():
      self.assertAllEqual([[20., 110.], [11., 11.]], features['price'].eval())

  def test_normalizer_fn_must_be_callable(self):
    with self.assertRaisesRegexp(TypeError, 'must be a callable'):
      fc.numeric_column('price', normalizer_fn='NotACallable')

  def test_normalizer_fn_transform_feature(self):

    def _increment_two(input_tensor):
      return input_tensor + 2.

    price = fc.numeric_column('price', shape=[2], normalizer_fn=_increment_two)
    builder = fc._LazyBuilder({
        'price': [[1., 2.], [5., 6.]]
    })
    output = builder.get(price)
    with self.test_session():
      self.assertAllEqual([[3., 4.], [7., 8.]], output.eval())

  def test_get_dense_tensor(self):

    def _increment_two(input_tensor):
      return input_tensor + 2.

    price = fc.numeric_column('price', shape=[2], normalizer_fn=_increment_two)
    builder = fc._LazyBuilder({
        'price': [[1., 2.], [5., 6.]]
    })
    self.assertEqual(builder.get(price), price._get_dense_tensor(builder))

  def test_sparse_tensor_not_supported(self):
    price = fc.numeric_column('price')
    builder = fc._LazyBuilder({
        'price':
            sparse_tensor.SparseTensor(
                indices=[[0, 0]], values=[0.3], dense_shape=[1, 1])
    })
    with self.assertRaisesRegexp(ValueError, 'must be a Tensor'):
      price._transform_feature(builder)

  def test_deep_copy(self):
    a = fc.numeric_column('aaa', shape=[1, 2], default_value=[[3., 2.]])
    a_copy = copy.deepcopy(a)
    self.assertEqual(a_copy.name, 'aaa')
    self.assertEqual(a_copy.shape, (1, 2))
    self.assertEqual(a_copy.default_value, ((3., 2.),))

  def test_numpy_default_value(self):
    a = fc.numeric_column(
        'aaa', shape=[1, 2], default_value=np.array([[3., 2.]]))
    self.assertEqual(a.default_value, ((3., 2.),))

  def test_make_linear_model(self):
    price = fc.numeric_column('price')
    with ops.Graph().as_default():
      features = {'price': [[1.], [5.]]}
      predictions = fc.make_linear_model(features, [price])
      bias = get_linear_model_bias()
      price_var = get_linear_model_column_var(price)
      with _initialized_session() as sess:
        self.assertAllClose([0.], bias.eval())
        self.assertAllClose([[0.]], price_var.eval())
        self.assertAllClose([[0.], [0.]], predictions.eval())
        sess.run(price_var.assign([[10.]]))
        self.assertAllClose([[10.], [50.]], predictions.eval())


class BucketizedColumnTest(test.TestCase):

  def test_invalid_source_column_type(self):
    a = fc.categorical_column_with_hash_bucket('aaa', hash_bucket_size=10)
    with self.assertRaisesRegexp(
        ValueError,
        'source_column must be a column generated with numeric_column'):
      fc.bucketized_column(a, boundaries=[0, 1])

  def test_invalid_source_column_shape(self):
    a = fc.numeric_column('aaa', shape=[2, 3])
    with self.assertRaisesRegexp(
        ValueError, 'source_column must be one-dimensional column'):
      fc.bucketized_column(a, boundaries=[0, 1])

  def test_invalid_boundaries(self):
    a = fc.numeric_column('aaa')
    with self.assertRaisesRegexp(
        ValueError, 'boundaries must be a sorted list'):
      fc.bucketized_column(a, boundaries=None)
    with self.assertRaisesRegexp(
        ValueError, 'boundaries must be a sorted list'):
      fc.bucketized_column(a, boundaries=1.)
    with self.assertRaisesRegexp(
        ValueError, 'boundaries must be a sorted list'):
      fc.bucketized_column(a, boundaries=[1, 0])
    with self.assertRaisesRegexp(
        ValueError, 'boundaries must be a sorted list'):
      fc.bucketized_column(a, boundaries=[1, 1])

  def test_name(self):
    a = fc.numeric_column('aaa', dtype=dtypes.int32)
    b = fc.bucketized_column(a, boundaries=[0, 1])
    self.assertEqual('aaa_bucketized', b.name)

  def test_parse_config(self):
    a = fc.numeric_column('aaa', shape=[2], dtype=dtypes.int32)
    b = fc.bucketized_column(a, boundaries=[0, 1])
    self.assertEqual({
        'aaa': parsing_ops.FixedLenFeature((2,), dtype=dtypes.int32)
    }, b._parse_example_config)

  def test_variable_shape(self):
    a = fc.numeric_column('aaa', shape=[2], dtype=dtypes.int32)
    b = fc.bucketized_column(a, boundaries=[0, 1])
    # Column 'aaa` has shape [2] times three buckets -> variable_shape=[2, 3].
    self.assertAllEqual((2, 3), b._variable_shape)

  def test_num_buckets(self):
    a = fc.numeric_column('aaa', shape=[2], dtype=dtypes.int32)
    b = fc.bucketized_column(a, boundaries=[0, 1])
    # Column 'aaa` has shape [2] times three buckets -> num_buckets=6.
    self.assertEqual(6, b._num_buckets)

  def test_parse_example(self):
    price = fc.numeric_column('price', shape=[2])
    bucketized_price = fc.bucketized_column(price, boundaries=[0, 50])
    data = example_pb2.Example(features=feature_pb2.Features(
        feature={
            'price':
                feature_pb2.Feature(float_list=feature_pb2.FloatList(
                    value=[20., 110.]))
        }))
    features = parsing_ops.parse_example(
        serialized=[data.SerializeToString()],
        features=bucketized_price._parse_example_config)
    self.assertIn('price', features)
    with self.test_session():
      self.assertAllEqual([[20., 110.]], features['price'].eval())

  def test_transform_feature(self):
    price = fc.numeric_column('price', shape=[2])
    bucketized_price = fc.bucketized_column(price, boundaries=[0, 2, 4, 6])
    with ops.Graph().as_default():
      builder = fc._LazyBuilder({
          'price': [[-1., 1.], [5., 6.]]
      })
      transformed_tensor = builder.get(bucketized_price)
      with _initialized_session():
        self.assertAllEqual([[0, 1], [3, 4]], transformed_tensor.eval())

  def test_get_dense_tensor_one_input_value(self):
    """Tests _get_dense_tensor() for input with shape=[1]."""
    price = fc.numeric_column('price', shape=[1])
    bucketized_price = fc.bucketized_column(price, boundaries=[0, 2, 4, 6])
    with ops.Graph().as_default():
      builder = fc._LazyBuilder({
          'price': [[-1.], [1.], [5.], [6.]]
      })
      with _initialized_session():
        bucketized_price_tensor = bucketized_price._get_dense_tensor(builder)
        self.assertAllClose(
            # One-hot tensor.
            [[[1., 0., 0., 0., 0.]],
             [[0., 1., 0., 0., 0.]],
             [[0., 0., 0., 1., 0.]],
             [[0., 0., 0., 0., 1.]]],
            bucketized_price_tensor.eval())

  def test_get_dense_tensor_two_input_values(self):
    """Tests _get_dense_tensor() for input with shape=[2]."""
    price = fc.numeric_column('price', shape=[2])
    bucketized_price = fc.bucketized_column(price, boundaries=[0, 2, 4, 6])
    with ops.Graph().as_default():
      builder = fc._LazyBuilder({
          'price': [[-1., 1.], [5., 6.]]
      })
      with _initialized_session():
        bucketized_price_tensor = bucketized_price._get_dense_tensor(builder)
        self.assertAllClose(
            # One-hot tensor.
            [[[1., 0., 0., 0., 0.], [0., 1., 0., 0., 0.]],
             [[0., 0., 0., 1., 0.], [0., 0., 0., 0., 1.]]],
            bucketized_price_tensor.eval())

  def test_get_sparse_tensors_one_input_value(self):
    """Tests _get_sparse_tensors() for input with shape=[1]."""
    price = fc.numeric_column('price', shape=[1])
    bucketized_price = fc.bucketized_column(price, boundaries=[0, 2, 4, 6])
    with ops.Graph().as_default():
      builder = fc._LazyBuilder({
          'price': [[-1.], [1.], [5.], [6.]]
      })
      with _initialized_session() as sess:
        id_weight_pair = bucketized_price._get_sparse_tensors(builder)
        self.assertIsNone(id_weight_pair.weight_tensor)
        id_tensor_value = sess.run(id_weight_pair.id_tensor)
        self.assertAllEqual(
            [[0, 0], [1, 0], [2, 0], [3, 0]], id_tensor_value.indices)
        self.assertAllEqual([0, 1, 3, 4], id_tensor_value.values)
        self.assertAllEqual([4, 1], id_tensor_value.dense_shape)

  def test_get_sparse_tensors_two_input_values(self):
    """Tests _get_sparse_tensors() for input with shape=[2]."""
    price = fc.numeric_column('price', shape=[2])
    bucketized_price = fc.bucketized_column(price, boundaries=[0, 2, 4, 6])
    with ops.Graph().as_default():
      builder = fc._LazyBuilder({
          'price': [[-1., 1.], [5., 6.]]
      })
      with _initialized_session() as sess:
        id_weight_pair = bucketized_price._get_sparse_tensors(builder)
        self.assertIsNone(id_weight_pair.weight_tensor)
        id_tensor_value = sess.run(id_weight_pair.id_tensor)
        self.assertAllEqual(
            [[0, 0], [0, 1], [1, 0], [1, 1]], id_tensor_value.indices)
        # Values 0-4 correspond to the first column of the input price.
        # Values 5-9 correspond to the second column of the input price.
        self.assertAllEqual([0, 6, 3, 9], id_tensor_value.values)
        self.assertAllEqual([2, 2], id_tensor_value.dense_shape)

  def test_sparse_tensor_input_not_supported(self):
    price = fc.numeric_column('price')
    bucketized_price = fc.bucketized_column(price, boundaries=[0, 1])
    builder = fc._LazyBuilder({
        'price':
            sparse_tensor.SparseTensor(
                indices=[[0, 0]], values=[0.3], dense_shape=[1, 1])
    })
    with self.assertRaisesRegexp(ValueError, 'must be a Tensor'):
      bucketized_price._transform_feature(builder)

  def test_deep_copy(self):
    a = fc.numeric_column('aaa', shape=[2])
    a_bucketized = fc.bucketized_column(a, boundaries=[0, 1])
    a_bucketized_copy = copy.deepcopy(a_bucketized)
    self.assertEqual(a_bucketized_copy.name, 'aaa_bucketized')
    self.assertAllEqual(a_bucketized_copy._variable_shape, (2, 3))
    self.assertEqual(a_bucketized_copy.boundaries, (0, 1))

  def test_make_linear_model_one_input_value(self):
    """Tests make_linear_model() for input with shape=[1]."""
    price = fc.numeric_column('price', shape=[1])
    bucketized_price = fc.bucketized_column(price, boundaries=[0, 2, 4, 6])
    with ops.Graph().as_default():
      features = {'price': [[-1.], [1.], [5.], [6.]]}
      predictions = fc.make_linear_model(features, [bucketized_price])
      bias = get_linear_model_bias()
      bucketized_price_var = get_linear_model_column_var(bucketized_price)
      with _initialized_session() as sess:
        self.assertAllClose([0.], bias.eval())
        # One weight variable per bucket, all initialized to zero.
        self.assertAllClose(
            [[0.], [0.], [0.], [0.], [0.]], bucketized_price_var.eval())
        self.assertAllClose([[0.], [0.], [0.], [0.]], predictions.eval())
        sess.run(bucketized_price_var.assign(
            [[10.], [20.], [30.], [40.], [50.]]))
        # price -1. is in the 0th bucket, whose weight is 10.
        # price 1. is in the 1st bucket, whose weight is 20.
        # price 5. is in the 3rd bucket, whose weight is 40.
        # price 6. is in the 4th bucket, whose weight is 50.
        self.assertAllClose([[10.], [20.], [40.], [50.]], predictions.eval())
        sess.run(bias.assign([1.]))
        self.assertAllClose([[11.], [21.], [41.], [51.]], predictions.eval())

  def test_make_linear_model_two_input_values(self):
    """Tests make_linear_model() for input with shape=[2]."""
    price = fc.numeric_column('price', shape=[2])
    bucketized_price = fc.bucketized_column(price, boundaries=[0, 2, 4, 6])
    with ops.Graph().as_default():
      features = {'price': [[-1., 1.], [5., 6.]]}
      predictions = fc.make_linear_model(features, [bucketized_price])
      bias = get_linear_model_bias()
      bucketized_price_var = get_linear_model_column_var(bucketized_price)
      with _initialized_session() as sess:
        self.assertAllClose([0.], bias.eval())
        # One weight per bucket per input column, all initialized to zero.
        self.assertAllClose(
            [[0.], [0.], [0.], [0.], [0.], [0.], [0.], [0.], [0.], [0.]],
            bucketized_price_var.eval())
        self.assertAllClose([[0.], [0.]], predictions.eval())
        sess.run(bucketized_price_var.assign(
            [[10.], [20.], [30.], [40.], [50.],
             [60.], [70.], [80.], [90.], [100.]]))
        # 1st example:
        #   price -1. is in the 0th bucket, whose weight is 10.
        #   price 1. is in the 6th bucket, whose weight is 70.
        # 2nd example:
        #   price 5. is in the 3rd bucket, whose weight is 40.
        #   price 6. is in the 9th bucket, whose weight is 100.
        self.assertAllClose([[80.], [140.]], predictions.eval())
        sess.run(bias.assign([1.]))
        self.assertAllClose([[81.], [141.]], predictions.eval())


class HashedCategoricalColumnTest(test.TestCase):

  def test_defaults(self):
    a = fc.categorical_column_with_hash_bucket('aaa', 10)
    self.assertEqual('aaa', a.name)
    self.assertEqual('aaa', a.key)
    self.assertEqual(10, a.hash_bucket_size)
    self.assertEqual(dtypes.string, a.dtype)

  def test_bucket_size_should_be_given(self):
    with self.assertRaisesRegexp(ValueError, 'hash_bucket_size must be set.'):
      fc.categorical_column_with_hash_bucket('aaa', None)

  def test_bucket_size_should_be_positive(self):
    with self.assertRaisesRegexp(ValueError,
                                 'hash_bucket_size must be at least 1'):
      fc.categorical_column_with_hash_bucket('aaa', 0)

  def test_dtype_should_be_string_or_integer(self):
    fc.categorical_column_with_hash_bucket('aaa', 10, dtype=dtypes.string)
    fc.categorical_column_with_hash_bucket('aaa', 10, dtype=dtypes.int32)
    with self.assertRaisesRegexp(ValueError, 'dtype must be string or integer'):
      fc.categorical_column_with_hash_bucket('aaa', 10, dtype=dtypes.float32)

  def test_deep_copy(self):
    """Tests deepcopy of categorical_column_with_hash_bucket."""
    original = fc.categorical_column_with_hash_bucket('aaa', 10)
    for column in (original, copy.deepcopy(original)):
      self.assertEqual('aaa', column.name)
      self.assertEqual(10, column.hash_bucket_size)
      # pylint: disable=protected-access
      self.assertEqual(10, column._num_buckets)
      # pylint: enable=protected-access
      self.assertEqual(dtypes.string, column.dtype)

  def test_parse_config(self):
    a = fc.categorical_column_with_hash_bucket('aaa', 10)
    self.assertEqual({
        'aaa': parsing_ops.VarLenFeature(dtypes.string)
    }, a._parse_example_config)

  def test_parse_config_int(self):
    a = fc.categorical_column_with_hash_bucket('aaa', 10, dtype=dtypes.int32)
    self.assertEqual({
        'aaa': parsing_ops.VarLenFeature(dtypes.int32)
    }, a._parse_example_config)

  def test_strings_should_be_hashed(self):
    hashed_sparse = fc.categorical_column_with_hash_bucket('wire', 10)
    wire_tensor = sparse_tensor.SparseTensor(
        values=['omar', 'stringer', 'marlo'],
        indices=[[0, 0], [1, 0], [1, 1]],
        dense_shape=[2, 2])
    builder = fc._LazyBuilder({'wire': wire_tensor})
    output = builder.get(hashed_sparse)
    # Check exact hashed output. If hashing changes this test will break.
    expected_values = [6, 4, 1]
    with self.test_session():
      self.assertEqual(dtypes.int64, output.values.dtype)
      self.assertAllEqual(expected_values, output.values.eval())
      self.assertAllEqual(wire_tensor.indices.eval(), output.indices.eval())
      self.assertAllEqual(wire_tensor.dense_shape.eval(),
                          output.dense_shape.eval())

  def test_tensor_dtype_should_be_string_or_integer(self):
    string_fc = fc.categorical_column_with_hash_bucket(
        'a_string', 10, dtype=dtypes.string)
    int_fc = fc.categorical_column_with_hash_bucket(
        'a_int', 10, dtype=dtypes.int32)
    float_fc = fc.categorical_column_with_hash_bucket(
        'a_float', 10, dtype=dtypes.string)
    int_tensor = sparse_tensor.SparseTensor(
        values=[101],
        indices=[[0, 0]],
        dense_shape=[1, 1])
    string_tensor = sparse_tensor.SparseTensor(
        values=['101'],
        indices=[[0, 0]],
        dense_shape=[1, 1])
    float_tensor = sparse_tensor.SparseTensor(
        values=[101.],
        indices=[[0, 0]],
        dense_shape=[1, 1])
    builder = fc._LazyBuilder({
        'a_int': int_tensor,
        'a_string': string_tensor,
        'a_float': float_tensor
    })
    builder.get(string_fc)
    builder.get(int_fc)
    with self.assertRaisesRegexp(ValueError, 'dtype must be string or integer'):
      builder.get(float_fc)

  def test_dtype_should_match_with_tensor(self):
    hashed_sparse = fc.categorical_column_with_hash_bucket(
        'wire', 10, dtype=dtypes.int64)
    wire_tensor = sparse_tensor.SparseTensor(
        values=['omar'], indices=[[0, 0]], dense_shape=[1, 1])
    builder = fc._LazyBuilder({'wire': wire_tensor})
    with self.assertRaisesRegexp(ValueError, 'dtype must be compatible'):
      builder.get(hashed_sparse)

  def test_ints_should_be_hashed(self):
    hashed_sparse = fc.categorical_column_with_hash_bucket(
        'wire', 10, dtype=dtypes.int64)
    wire_tensor = sparse_tensor.SparseTensor(
        values=[101, 201, 301],
        indices=[[0, 0], [1, 0], [1, 1]],
        dense_shape=[2, 2])
    builder = fc._LazyBuilder({'wire': wire_tensor})
    output = builder.get(hashed_sparse)
    # Check exact hashed output. If hashing changes this test will break.
    expected_values = [3, 7, 5]
    with self.test_session():
      self.assertAllEqual(expected_values, output.values.eval())

  def test_int32_64_is_compatible(self):
    hashed_sparse = fc.categorical_column_with_hash_bucket(
        'wire', 10, dtype=dtypes.int64)
    wire_tensor = sparse_tensor.SparseTensor(
        values=constant_op.constant([101, 201, 301], dtype=dtypes.int32),
        indices=[[0, 0], [1, 0], [1, 1]],
        dense_shape=[2, 2])
    builder = fc._LazyBuilder({'wire': wire_tensor})
    output = builder.get(hashed_sparse)
    # Check exact hashed output. If hashing changes this test will break.
    expected_values = [3, 7, 5]
    with self.test_session():
      self.assertAllEqual(expected_values, output.values.eval())

  def test_get_sparse_tensors(self):
    hashed_sparse = fc.categorical_column_with_hash_bucket('wire', 10)
    builder = fc._LazyBuilder({
        'wire': sparse_tensor.SparseTensor(
            values=['omar', 'stringer', 'marlo'],
            indices=[[0, 0], [1, 0], [1, 1]],
            dense_shape=[2, 2])
    })
    id_weight_pair = hashed_sparse._get_sparse_tensors(builder)
    self.assertIsNone(id_weight_pair.weight_tensor)
    self.assertEqual(builder.get(hashed_sparse), id_weight_pair.id_tensor)

  def test_get_sparse_tensors_dense_input(self):
    hashed_sparse = fc.categorical_column_with_hash_bucket('wire', 10)
    builder = fc._LazyBuilder({
        'wire': (('omar', ''), ('stringer', 'marlo'))
    })
    id_weight_pair = hashed_sparse._get_sparse_tensors(builder)
    self.assertIsNone(id_weight_pair.weight_tensor)
    self.assertEqual(builder.get(hashed_sparse), id_weight_pair.id_tensor)

  def test_make_linear_model(self):
    wire_column = fc.categorical_column_with_hash_bucket('wire', 4)
    self.assertEqual(4, wire_column._num_buckets)
    with ops.Graph().as_default():
      predictions = fc.make_linear_model({
          wire_column.name: sparse_tensor.SparseTensorValue(
              indices=((0, 0), (1, 0), (1, 1)),
              values=('marlo', 'skywalker', 'omar'),
              dense_shape=(2, 2))
      }, (wire_column,))
      bias = get_linear_model_bias()
      wire_var = get_linear_model_column_var(wire_column)
      with _initialized_session():
        self.assertAllClose((0.,), bias.eval())
        self.assertAllClose(((0.,), (0.,), (0.,), (0.,)), wire_var.eval())
        self.assertAllClose(((0.,), (0.,)), predictions.eval())
        wire_var.assign(((1.,), (2.,), (3.,), (4.,))).eval()
        # 'marlo' -> 3: wire_var[3] = 4
        # 'skywalker' -> 2, 'omar' -> 2: wire_var[2] + wire_var[2] = 3+3 = 6
        self.assertAllClose(((4.,), (6.,)), predictions.eval())


def get_linear_model_bias():
  with variable_scope.variable_scope('make_linear_model', reuse=True):
    return variable_scope.get_variable('bias_weight')


def get_linear_model_column_var(column):
  return ops.get_collection(ops.GraphKeys.GLOBAL_VARIABLES,
                            'make_linear_model/' + column.name)[0]


class MakeLinearModelTest(test.TestCase):

  def test_should_be_feature_column(self):
    with self.assertRaisesRegexp(ValueError, 'must be a _FeatureColumn'):
      fc.make_linear_model(
          features={'a': [[0]]}, feature_columns='NotSupported')

  def test_should_be_dense_or_categorical_column(self):

    class NotSupportedColumn(fc._FeatureColumn):

      @property
      def name(self):
        return 'NotSupportedColumn'

      def _transform_feature(self, cache):
        pass

      @property
      def _parse_example_config(self):
        pass

    with self.assertRaisesRegexp(
        ValueError, 'must be either a _DenseColumn or _CategoricalColumn'):
      fc.make_linear_model(
          features={'a': [[0]]}, feature_columns=[NotSupportedColumn()])

  def test_does_not_support_dict_columns(self):
    with self.assertRaisesRegexp(
        ValueError, 'Expected feature_columns to be iterable, found dict.'):
      fc.make_linear_model(
          features={'a': [[0]]}, feature_columns={'a': fc.numeric_column('a')})

  def test_raises_if_duplicate_name(self):
    with self.assertRaisesRegexp(
        ValueError, 'Duplicate feature column name found for columns'):
      fc.make_linear_model(
          features={'a': [[0]]},
          feature_columns=[fc.numeric_column('a'),
                           fc.numeric_column('a')])

  def test_dense_bias(self):
    price = fc.numeric_column('price')
    with ops.Graph().as_default():
      features = {'price': [[1.], [5.]]}
      predictions = fc.make_linear_model(features, [price])
      bias = get_linear_model_bias()
      price_var = get_linear_model_column_var(price)
      with _initialized_session() as sess:
        self.assertAllClose([0.], bias.eval())
        sess.run(price_var.assign([[10.]]))
        sess.run(bias.assign([5.]))
        self.assertAllClose([[15.], [55.]], predictions.eval())

  def test_sparse_bias(self):
    wire_cast = fc.categorical_column_with_hash_bucket('wire_cast', 4)
    with ops.Graph().as_default():
      wire_tensor = sparse_tensor.SparseTensor(
          values=['omar', 'stringer', 'marlo'],  # hashed to = [2, 0, 3]
          indices=[[0, 0], [1, 0], [1, 1]],
          dense_shape=[2, 2])
      features = {'wire_cast': wire_tensor}
      predictions = fc.make_linear_model(features, [wire_cast])
      bias = get_linear_model_bias()
      wire_cast_var = get_linear_model_column_var(wire_cast)
      with _initialized_session() as sess:
        self.assertAllClose([0.], bias.eval())
        self.assertAllClose([[0.], [0.], [0.], [0.]], wire_cast_var.eval())
        sess.run(wire_cast_var.assign([[10.], [100.], [1000.], [10000.]]))
        sess.run(bias.assign([5.]))
        self.assertAllClose([[1005.], [10015.]], predictions.eval())

  def test_dense_and_sparse_bias(self):
    wire_cast = fc.categorical_column_with_hash_bucket('wire_cast', 4)
    price = fc.numeric_column('price')
    with ops.Graph().as_default():
      wire_tensor = sparse_tensor.SparseTensor(
          values=['omar', 'stringer', 'marlo'],  # hashed to = [2, 0, 3]
          indices=[[0, 0], [1, 0], [1, 1]],
          dense_shape=[2, 2])
      features = {'wire_cast': wire_tensor, 'price': [[1.], [5.]]}
      predictions = fc.make_linear_model(features, [wire_cast, price])
      bias = get_linear_model_bias()
      wire_cast_var = get_linear_model_column_var(wire_cast)
      price_var = get_linear_model_column_var(price)
      with _initialized_session() as sess:
        sess.run(wire_cast_var.assign([[10.], [100.], [1000.], [10000.]]))
        sess.run(bias.assign([5.]))
        sess.run(price_var.assign([[10.]]))
        self.assertAllClose([[1015.], [10065.]], predictions.eval())

  def test_dense_and_sparse_column(self):
    """When the column is both dense and sparse, uses sparse tensors."""

    class _DenseAndSparseColumn(fc._DenseColumn, fc._CategoricalColumn):

      @property
      def name(self):
        return 'dense_and_sparse_column'

      @property
      def _parse_example_config(self):
        return {self.name: parsing_ops.VarLenFeature(self.dtype)}

      def _transform_feature(self, inputs):
        return inputs.get(self.name)

      @property
      def _variable_shape(self):
        raise ValueError('Should not use this method.')

      def _get_dense_tensor(self, inputs, weight_collections=None,
                            trainable=None):
        raise ValueError('Should not use this method.')

      @property
      def _num_buckets(self):
        return 4

      def _get_sparse_tensors(self, inputs, weight_collections=None,
                              trainable=None):
        sp_tensor = sparse_tensor.SparseTensor(
            indices=[[0, 0], [1, 0], [1, 1]],
            values=[2, 0, 3],
            dense_shape=[2, 2])
        return fc._CategoricalColumn.IdWeightPair(sp_tensor, None)

    dense_and_sparse_column = _DenseAndSparseColumn()
    with ops.Graph().as_default():
      sp_tensor = sparse_tensor.SparseTensor(
          values=['omar', 'stringer', 'marlo'],
          indices=[[0, 0], [1, 0], [1, 1]],
          dense_shape=[2, 2])
      features = {dense_and_sparse_column.name: sp_tensor}
      predictions = fc.make_linear_model(features, [dense_and_sparse_column])
      bias = get_linear_model_bias()
      dense_and_sparse_column_var = get_linear_model_column_var(
          dense_and_sparse_column)
      with _initialized_session() as sess:
        sess.run(dense_and_sparse_column_var.assign(
            [[10.], [100.], [1000.], [10000.]]))
        sess.run(bias.assign([5.]))
        self.assertAllClose([[1005.], [10015.]], predictions.eval())

  def test_dense_multi_output(self):
    price = fc.numeric_column('price')
    with ops.Graph().as_default():
      features = {'price': [[1.], [5.]]}
      predictions = fc.make_linear_model(features, [price], units=3)
      bias = get_linear_model_bias()
      price_var = get_linear_model_column_var(price)
      with _initialized_session() as sess:
        self.assertAllClose([0., 0., 0.], bias.eval())
        self.assertAllClose([[0., 0., 0.]], price_var.eval())
        sess.run(price_var.assign([[10., 100., 1000.]]))
        sess.run(bias.assign([5., 6., 7.]))
        self.assertAllClose([[15., 106., 1007.], [55., 506., 5007.]],
                            predictions.eval())

  def test_sparse_multi_output(self):
    wire_cast = fc.categorical_column_with_hash_bucket('wire_cast', 4)
    with ops.Graph().as_default():
      wire_tensor = sparse_tensor.SparseTensor(
          values=['omar', 'stringer', 'marlo'],  # hashed to = [2, 0, 3]
          indices=[[0, 0], [1, 0], [1, 1]],
          dense_shape=[2, 2])
      features = {'wire_cast': wire_tensor}
      predictions = fc.make_linear_model(features, [wire_cast], units=3)
      bias = get_linear_model_bias()
      wire_cast_var = get_linear_model_column_var(wire_cast)
      with _initialized_session() as sess:
        self.assertAllClose([0., 0., 0.], bias.eval())
        self.assertAllClose([[0.] * 3] * 4, wire_cast_var.eval())
        sess.run(
            wire_cast_var.assign([[10., 11., 12.], [100., 110., 120.], [
                1000., 1100., 1200.
            ], [10000., 11000., 12000.]]))
        sess.run(bias.assign([5., 6., 7.]))
        self.assertAllClose([[1005., 1106., 1207.], [10015., 11017., 12019.]],
                            predictions.eval())

  def test_dense_multi_dimension(self):
    price = fc.numeric_column('price', shape=2)
    with ops.Graph().as_default():
      features = {'price': [[1., 2.], [5., 6.]]}
      predictions = fc.make_linear_model(features, [price])
      price_var = get_linear_model_column_var(price)
      with _initialized_session() as sess:
        self.assertAllClose([[0.], [0.]], price_var.eval())
        sess.run(price_var.assign([[10.], [100.]]))
        self.assertAllClose([[210.], [650.]], predictions.eval())

  def test_sparse_combiner(self):
    wire_cast = fc.categorical_column_with_hash_bucket('wire_cast', 4)
    with ops.Graph().as_default():
      wire_tensor = sparse_tensor.SparseTensor(
          values=['omar', 'stringer', 'marlo'],  # hashed to = [2, 0, 3]
          indices=[[0, 0], [1, 0], [1, 1]],
          dense_shape=[2, 2])
      features = {'wire_cast': wire_tensor}
      predictions = fc.make_linear_model(
          features, [wire_cast], sparse_combiner='mean')
      bias = get_linear_model_bias()
      wire_cast_var = get_linear_model_column_var(wire_cast)
      with _initialized_session() as sess:
        sess.run(wire_cast_var.assign([[10.], [100.], [1000.], [10000.]]))
        sess.run(bias.assign([5.]))
        self.assertAllClose([[1005.], [5010.]], predictions.eval())

  def test_dense_multi_dimension_multi_output(self):
    price = fc.numeric_column('price', shape=2)
    with ops.Graph().as_default():
      features = {'price': [[1., 2.], [5., 6.]]}
      predictions = fc.make_linear_model(features, [price], units=3)
      bias = get_linear_model_bias()
      price_var = get_linear_model_column_var(price)
      with _initialized_session() as sess:
        self.assertAllClose([0., 0., 0.], bias.eval())
        self.assertAllClose([[0., 0., 0.], [0., 0., 0.]], price_var.eval())
        sess.run(price_var.assign([[1., 2., 3.], [10., 100., 1000.]]))
        sess.run(bias.assign([2., 3., 4.]))
        self.assertAllClose([[23., 205., 2007.], [67., 613., 6019.]],
                            predictions.eval())

  def test_raises_if_shape_mismatch(self):
    price = fc.numeric_column('price', shape=2)
    with ops.Graph().as_default():
      features = {'price': [[1.], [5.]]}
      predictions = fc.make_linear_model(features, [price])
      with _initialized_session():
        with self.assertRaisesRegexp(Exception, 'requested shape has 4'):
          predictions.eval()

  def test_dense_reshaping(self):
    price = fc.numeric_column('price', shape=[1, 2])
    with ops.Graph().as_default():
      features = {'price': [[[1., 2.]], [[5., 6.]]]}
      predictions = fc.make_linear_model(features, [price])
      bias = get_linear_model_bias()
      price_var = get_linear_model_column_var(price)
      with _initialized_session() as sess:
        self.assertAllClose([0.], bias.eval())
        self.assertAllClose([[0.], [0.]], price_var.eval())
        self.assertAllClose([[0.], [0.]], predictions.eval())
        sess.run(price_var.assign([[10.], [100.]]))
        self.assertAllClose([[210.], [650.]], predictions.eval())

  def test_dense_multi_column(self):
    price1 = fc.numeric_column('price1', shape=2)
    price2 = fc.numeric_column('price2')
    with ops.Graph().as_default():
      features = {
          'price1': [[1., 2.], [5., 6.]],
          'price2': [[3.], [4.]]
      }
      predictions = fc.make_linear_model(features, [price1, price2])
      bias = get_linear_model_bias()
      price1_var = get_linear_model_column_var(price1)
      price2_var = get_linear_model_column_var(price2)
      with _initialized_session() as sess:
        self.assertAllClose([0.], bias.eval())
        self.assertAllClose([[0.], [0.]], price1_var.eval())
        self.assertAllClose([[0.]], price2_var.eval())
        self.assertAllClose([[0.], [0.]], predictions.eval())
        sess.run(price1_var.assign([[10.], [100.]]))
        sess.run(price2_var.assign([[1000.]]))
        sess.run(bias.assign([7.]))
        self.assertAllClose([[3217.], [4657.]], predictions.eval())

  def test_dense_collection(self):
    price = fc.numeric_column('price')
    with ops.Graph().as_default() as g:
      features = {'price': [[1.], [5.]]}
      fc.make_linear_model(features, [price], weight_collections=['my-vars'])
      my_vars = g.get_collection('my-vars')
      bias = get_linear_model_bias()
      price_var = get_linear_model_column_var(price)
      self.assertIn(bias, my_vars)
      self.assertIn(price_var, my_vars)

  def test_sparse_collection(self):
    wire_cast = fc.categorical_column_with_hash_bucket('wire_cast', 4)
    with ops.Graph().as_default() as g:
      wire_tensor = sparse_tensor.SparseTensor(
          values=['omar'], indices=[[0, 0]], dense_shape=[1, 1])
      features = {'wire_cast': wire_tensor}
      fc.make_linear_model(
          features, [wire_cast], weight_collections=['my-vars'])
      my_vars = g.get_collection('my-vars')
      bias = get_linear_model_bias()
      wire_cast_var = get_linear_model_column_var(wire_cast)
      self.assertIn(bias, my_vars)
      self.assertIn(wire_cast_var, my_vars)

  def test_dense_trainable_default(self):
    price = fc.numeric_column('price')
    with ops.Graph().as_default() as g:
      features = {'price': [[1.], [5.]]}
      fc.make_linear_model(features, [price])
      bias = get_linear_model_bias()
      price_var = get_linear_model_column_var(price)
      trainable_vars = g.get_collection(ops.GraphKeys.TRAINABLE_VARIABLES)
      self.assertIn(bias, trainable_vars)
      self.assertIn(price_var, trainable_vars)

  def test_sparse_trainable_default(self):
    wire_cast = fc.categorical_column_with_hash_bucket('wire_cast', 4)
    with ops.Graph().as_default() as g:
      wire_tensor = sparse_tensor.SparseTensor(
          values=['omar'], indices=[[0, 0]], dense_shape=[1, 1])
      features = {'wire_cast': wire_tensor}
      fc.make_linear_model(features, [wire_cast])
      trainable_vars = g.get_collection(ops.GraphKeys.TRAINABLE_VARIABLES)
      bias = get_linear_model_bias()
      wire_cast_var = get_linear_model_column_var(wire_cast)
      self.assertIn(bias, trainable_vars)
      self.assertIn(wire_cast_var, trainable_vars)

  def test_dense_trainable_false(self):
    price = fc.numeric_column('price')
    with ops.Graph().as_default() as g:
      features = {'price': [[1.], [5.]]}
      fc.make_linear_model(features, [price], trainable=False)
      trainable_vars = g.get_collection(ops.GraphKeys.TRAINABLE_VARIABLES)
      self.assertEqual([], trainable_vars)

  def test_sparse_trainable_false(self):
    wire_cast = fc.categorical_column_with_hash_bucket('wire_cast', 4)
    with ops.Graph().as_default() as g:
      wire_tensor = sparse_tensor.SparseTensor(
          values=['omar'], indices=[[0, 0]], dense_shape=[1, 1])
      features = {'wire_cast': wire_tensor}
      fc.make_linear_model(features, [wire_cast], trainable=False)
      trainable_vars = g.get_collection(ops.GraphKeys.TRAINABLE_VARIABLES)
      self.assertEqual([], trainable_vars)

  def test_column_order(self):
    price_a = fc.numeric_column('price_a')
    price_b = fc.numeric_column('price_b')
    wire_cast = fc.categorical_column_with_hash_bucket('wire_cast', 4)
    with ops.Graph().as_default() as g:
      features = {
          'price_a': [[1.]],
          'price_b': [[3.]],
          'wire_cast':
              sparse_tensor.SparseTensor(
                  values=['omar'], indices=[[0, 0]], dense_shape=[1, 1])
      }
      fc.make_linear_model(
          features, [price_a, wire_cast, price_b],
          weight_collections=['my-vars'])
      my_vars = g.get_collection('my-vars')
      self.assertIn('price_a', my_vars[0].name)
      self.assertIn('price_b', my_vars[1].name)
      self.assertIn('wire_cast', my_vars[2].name)

    with ops.Graph().as_default() as g:
      features = {
          'price_a': [[1.]],
          'price_b': [[3.]],
          'wire_cast':
              sparse_tensor.SparseTensor(
                  values=['omar'], indices=[[0, 0]], dense_shape=[1, 1])
      }
      fc.make_linear_model(
          features, [wire_cast, price_b, price_a],
          weight_collections=['my-vars'])
      my_vars = g.get_collection('my-vars')
      self.assertIn('price_a', my_vars[0].name)
      self.assertIn('price_b', my_vars[1].name)
      self.assertIn('wire_cast', my_vars[2].name)


class MakeInputLayerTest(test.TestCase):

  def test_should_be_dense_column(self):
    with self.assertRaisesRegexp(ValueError, 'must be a _DenseColumn'):
      fc.make_input_layer(
          features={'a': [[0]]},
          feature_columns=[
              fc.categorical_column_with_hash_bucket('wire_cast', 4)
          ])

  def test_does_not_support_dict_columns(self):
    with self.assertRaisesRegexp(
        ValueError, 'Expected feature_columns to be iterable, found dict.'):
      fc.make_input_layer(
          features={'a': [[0]]}, feature_columns={'a': fc.numeric_column('a')})

  def test_raises_if_duplicate_name(self):
    with self.assertRaisesRegexp(
        ValueError, 'Duplicate feature column name found for columns'):
      fc.make_input_layer(
          features={'a': [[0]]},
          feature_columns=[fc.numeric_column('a'),
                           fc.numeric_column('a')])

  def test_one_column(self):
    price = fc.numeric_column('price')
    with ops.Graph().as_default():
      features = {'price': [[1.], [5.]]}
      net = fc.make_input_layer(features, [price])
      with _initialized_session():
        self.assertAllClose([[1.], [5.]], net.eval())

  def test_multi_dimension(self):
    price = fc.numeric_column('price', shape=2)
    with ops.Graph().as_default():
      features = {'price': [[1., 2.], [5., 6.]]}
      net = fc.make_input_layer(features, [price])
      with _initialized_session():
        self.assertAllClose([[1., 2.], [5., 6.]], net.eval())

  def test_raises_if_shape_mismatch(self):
    price = fc.numeric_column('price', shape=2)
    with ops.Graph().as_default():
      features = {'price': [[1.], [5.]]}
      net = fc.make_input_layer(features, [price])
      with _initialized_session():
        with self.assertRaisesRegexp(Exception, 'requested shape has 4'):
          net.eval()

  def test_reshaping(self):
    price = fc.numeric_column('price', shape=[1, 2])
    with ops.Graph().as_default():
      features = {'price': [[[1., 2.]], [[5., 6.]]]}
      net = fc.make_input_layer(features, [price])
      with _initialized_session():
        self.assertAllClose([[1., 2.], [5., 6.]], net.eval())

  def test_multi_column(self):
    price1 = fc.numeric_column('price1', shape=2)
    price2 = fc.numeric_column('price2')
    with ops.Graph().as_default():
      features = {
          'price1': [[1., 2.], [5., 6.]],
          'price2': [[3.], [4.]]
      }
      net = fc.make_input_layer(features, [price1, price2])
      with _initialized_session():
        self.assertAllClose([[1., 2., 3.], [5., 6., 4.]], net.eval())

  def test_column_order(self):
    price_a = fc.numeric_column('price_a')
    price_b = fc.numeric_column('price_b')
    with ops.Graph().as_default():
      features = {
          'price_a': [[1.]],
          'price_b': [[3.]],
      }
      net1 = fc.make_input_layer(features, [price_a, price_b])
      net2 = fc.make_input_layer(features, [price_b, price_a])
      with _initialized_session():
        self.assertAllClose([[1., 3.]], net1.eval())
        self.assertAllClose([[1., 3.]], net2.eval())


def _assert_sparse_tensor_value(test_case, expected, actual):
  test_case.assertEqual(np.int64, np.array(actual.indices).dtype)
  test_case.assertAllEqual(expected.indices, actual.indices)

  test_case.assertEqual(
      np.array(expected.values).dtype, np.array(actual.values).dtype)
  test_case.assertAllEqual(expected.values, actual.values)

  test_case.assertEqual(np.int64, np.array(actual.dense_shape).dtype)
  test_case.assertAllEqual(expected.dense_shape, actual.dense_shape)


class VocabularyFileCategoricalColumnTest(test.TestCase):

  def setUp(self):
    super(VocabularyFileCategoricalColumnTest, self).setUp()

    # Contains ints, Golden State Warriors jersey numbers: 30, 35, 11, 23, 22
    self._warriors_vocabulary_file_name = test.test_src_dir_path(
        'python/feature_column/testdata/warriors_vocabulary.txt')
    self._warriors_vocabulary_size = 5

    # Contains strings, character names from 'The Wire': omar, stringer, marlo
    self._wire_vocabulary_file_name = test.test_src_dir_path(
        'python/feature_column/testdata/wire_vocabulary.txt')
    self._wire_vocabulary_size = 3

  def test_defaults(self):
    column = fc.categorical_column_with_vocabulary_file(
        key='aaa', vocabulary_file='path_to_file', vocabulary_size=3)
    self.assertEqual('aaa', column.name)
    # pylint: disable=protected-access
    self.assertEqual(3, column._num_buckets)
    self.assertEqual({
        'aaa': parsing_ops.VarLenFeature(dtypes.string)
    }, column._parse_example_config)
    # pylint: enable=protected-access

  def test_all_constructor_args(self):
    column = fc.categorical_column_with_vocabulary_file(
        key='aaa', vocabulary_file='path_to_file', vocabulary_size=3,
        num_oov_buckets=4, dtype=dtypes.int32)
    # pylint: disable=protected-access
    self.assertEqual(7, column._num_buckets)
    self.assertEqual({
        'aaa': parsing_ops.VarLenFeature(dtypes.int32)
    }, column._parse_example_config)
    # pylint: enable=protected-access

  def test_deep_copy(self):
    """Tests deepcopy of categorical_column_with_hash_bucket."""
    original = fc.categorical_column_with_vocabulary_file(
        key='aaa', vocabulary_file='path_to_file', vocabulary_size=3,
        num_oov_buckets=4, dtype=dtypes.int32)
    for column in (original, copy.deepcopy(original)):
      self.assertEqual('aaa', column.name)
      # pylint: disable=protected-access
      self.assertEqual(7, column._num_buckets)
      self.assertEqual({
          'aaa': parsing_ops.VarLenFeature(dtypes.int32)
      }, column._parse_example_config)
      # pylint: enable=protected-access

  def test_vocabulary_file_none(self):
    with self.assertRaisesRegexp(ValueError, 'Missing vocabulary_file'):
      fc.categorical_column_with_vocabulary_file(
          key='aaa', vocabulary_file=None, vocabulary_size=3)

  def test_vocabulary_file_empty_string(self):
    with self.assertRaisesRegexp(ValueError, 'Missing vocabulary_file'):
      fc.categorical_column_with_vocabulary_file(
          key='aaa', vocabulary_file='', vocabulary_size=3)

  def test_invalid_vocabulary_file(self):
    column = fc.categorical_column_with_vocabulary_file(
        key='aaa', vocabulary_file='file_does_not_exist', vocabulary_size=10)
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1)),
        values=('marlo', 'skywalker', 'omar'),
        dense_shape=(2, 2))
    # pylint: disable=protected-access
    column._get_sparse_tensors(fc._LazyBuilder({'aaa': inputs}))
    # pylint: enable=protected-access
    with self.assertRaisesRegexp(errors.OpError, 'file_does_not_exist'):
      with self.test_session():
        lookup_ops.tables_initializer().run()

  def test_invalid_vocabulary_size(self):
    with self.assertRaisesRegexp(ValueError, 'Invalid vocabulary_size'):
      fc.categorical_column_with_vocabulary_file(
          key='aaa', vocabulary_file=self._wire_vocabulary_file_name,
          vocabulary_size=None)
    with self.assertRaisesRegexp(ValueError, 'Invalid vocabulary_size'):
      fc.categorical_column_with_vocabulary_file(
          key='aaa', vocabulary_file=self._wire_vocabulary_file_name,
          vocabulary_size=-1)
    with self.assertRaisesRegexp(ValueError, 'Invalid vocabulary_size'):
      fc.categorical_column_with_vocabulary_file(
          key='aaa', vocabulary_file=self._wire_vocabulary_file_name,
          vocabulary_size=0)

  def test_too_large_vocabulary_size(self):
    column = fc.categorical_column_with_vocabulary_file(
        key='aaa',
        vocabulary_file=self._wire_vocabulary_file_name,
        vocabulary_size=self._wire_vocabulary_size + 1)
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1)),
        values=('marlo', 'skywalker', 'omar'),
        dense_shape=(2, 2))
    # pylint: disable=protected-access
    column._get_sparse_tensors(fc._LazyBuilder({'aaa': inputs}))
    # pylint: enable=protected-access
    with self.assertRaisesRegexp(errors.OpError, 'Invalid vocab_size'):
      with self.test_session():
        lookup_ops.tables_initializer().run()

  def test_invalid_num_oov_buckets(self):
    with self.assertRaisesRegexp(ValueError, 'Invalid num_oov_buckets'):
      fc.categorical_column_with_vocabulary_file(
          key='aaa', vocabulary_file='path', vocabulary_size=3,
          num_oov_buckets=-1)

  def test_invalid_dtype(self):
    with self.assertRaisesRegexp(ValueError, 'dtype must be string or integer'):
      fc.categorical_column_with_vocabulary_file(
          key='aaa', vocabulary_file='path', vocabulary_size=3,
          dtype=dtypes.float64)

  def test_invalid_buckets_and_default_value(self):
    with self.assertRaisesRegexp(
        ValueError, 'both num_oov_buckets and default_value'):
      fc.categorical_column_with_vocabulary_file(
          key='aaa',
          vocabulary_file=self._wire_vocabulary_file_name,
          vocabulary_size=self._wire_vocabulary_size,
          num_oov_buckets=100,
          default_value=2)

  def test_invalid_input_dtype_int32(self):
    column = fc.categorical_column_with_vocabulary_file(
        key='aaa',
        vocabulary_file=self._wire_vocabulary_file_name,
        vocabulary_size=self._wire_vocabulary_size,
        dtype=dtypes.string)
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1)),
        values=(12, 24, 36),
        dense_shape=(2, 2))
    with self.assertRaisesRegexp(ValueError, 'dtype must be compatible'):
      # pylint: disable=protected-access
      column._get_sparse_tensors(fc._LazyBuilder({'aaa': inputs}))
      # pylint: enable=protected-access

  def test_invalid_input_dtype_string(self):
    column = fc.categorical_column_with_vocabulary_file(
        key='aaa',
        vocabulary_file=self._warriors_vocabulary_file_name,
        vocabulary_size=self._warriors_vocabulary_size,
        dtype=dtypes.int32)
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1)),
        values=('omar', 'stringer', 'marlo'),
        dense_shape=(2, 2))
    with self.assertRaisesRegexp(ValueError, 'dtype must be compatible'):
      # pylint: disable=protected-access
      column._get_sparse_tensors(fc._LazyBuilder({'aaa': inputs}))
      # pylint: enable=protected-access

  def test_get_sparse_tensors(self):
    column = fc.categorical_column_with_vocabulary_file(
        key='aaa',
        vocabulary_file=self._wire_vocabulary_file_name,
        vocabulary_size=self._wire_vocabulary_size)
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1)),
        values=('marlo', 'skywalker', 'omar'),
        dense_shape=(2, 2))
    # pylint: disable=protected-access
    id_weight_pair = column._get_sparse_tensors(
        fc._LazyBuilder({'aaa': inputs}))
    # pylint: enable=protected-access
    self.assertIsNone(id_weight_pair.weight_tensor)
    with _initialized_session():
      _assert_sparse_tensor_value(
          self,
          sparse_tensor.SparseTensorValue(
              indices=inputs.indices,
              values=np.array((2, -1, 0), dtype=np.int64),
              dense_shape=inputs.dense_shape),
          id_weight_pair.id_tensor.eval())

  def test_get_sparse_tensors_dense_input(self):
    column = fc.categorical_column_with_vocabulary_file(
        key='aaa',
        vocabulary_file=self._wire_vocabulary_file_name,
        vocabulary_size=self._wire_vocabulary_size)
    # pylint: disable=protected-access
    id_weight_pair = column._get_sparse_tensors(fc._LazyBuilder({
        'aaa': (('marlo', ''), ('skywalker', 'omar'))
    }))
    # pylint: enable=protected-access
    self.assertIsNone(id_weight_pair.weight_tensor)
    with _initialized_session():
      _assert_sparse_tensor_value(
          self,
          sparse_tensor.SparseTensorValue(
              indices=((0, 0), (1, 0), (1, 1)),
              values=np.array((2, -1, 0), dtype=np.int64),
              dense_shape=(2, 2)),
          id_weight_pair.id_tensor.eval())

  def test_get_sparse_tensors_default_value_in_vocabulary(self):
    column = fc.categorical_column_with_vocabulary_file(
        key='aaa',
        vocabulary_file=self._wire_vocabulary_file_name,
        vocabulary_size=self._wire_vocabulary_size,
        default_value=2)
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1)),
        values=('marlo', 'skywalker', 'omar'),
        dense_shape=(2, 2))
    # pylint: disable=protected-access
    id_weight_pair = column._get_sparse_tensors(
        fc._LazyBuilder({'aaa': inputs}))
    # pylint: enable=protected-access
    self.assertIsNone(id_weight_pair.weight_tensor)
    with _initialized_session():
      _assert_sparse_tensor_value(
          self,
          sparse_tensor.SparseTensorValue(
              indices=inputs.indices,
              values=np.array((2, 2, 0), dtype=np.int64),
              dense_shape=inputs.dense_shape),
          id_weight_pair.id_tensor.eval())

  def test_get_sparse_tensors_with_oov_buckets(self):
    column = fc.categorical_column_with_vocabulary_file(
        key='aaa',
        vocabulary_file=self._wire_vocabulary_file_name,
        vocabulary_size=self._wire_vocabulary_size,
        num_oov_buckets=100)
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1), (1, 2)),
        values=('marlo', 'skywalker', 'omar', 'heisenberg'),
        dense_shape=(2, 3))
    # pylint: disable=protected-access
    id_weight_pair = column._get_sparse_tensors(
        fc._LazyBuilder({'aaa': inputs}))
    # pylint: enable=protected-access
    self.assertIsNone(id_weight_pair.weight_tensor)
    with _initialized_session():
      _assert_sparse_tensor_value(
          self,
          sparse_tensor.SparseTensorValue(
              indices=inputs.indices,
              values=np.array((2, 33, 0, 62), dtype=np.int64),
              dense_shape=inputs.dense_shape),
          id_weight_pair.id_tensor.eval())

  def test_get_sparse_tensors_small_vocabulary_size(self):
    # 'marlo' is the last entry in our vocabulary file, so be setting
    # `vocabulary_size` to 1 less than number of entries in file, we take
    # 'marlo' out of the vocabulary.
    column = fc.categorical_column_with_vocabulary_file(
        key='aaa',
        vocabulary_file=self._wire_vocabulary_file_name,
        vocabulary_size=self._wire_vocabulary_size - 1)
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1)),
        values=('marlo', 'skywalker', 'omar'),
        dense_shape=(2, 2))
    # pylint: disable=protected-access
    id_weight_pair = column._get_sparse_tensors(
        fc._LazyBuilder({'aaa': inputs}))
    # pylint: enable=protected-access
    self.assertIsNone(id_weight_pair.weight_tensor)
    with _initialized_session():
      _assert_sparse_tensor_value(
          self,
          sparse_tensor.SparseTensorValue(
              indices=inputs.indices,
              values=np.array((-1, -1, 0), dtype=np.int64),
              dense_shape=inputs.dense_shape),
          id_weight_pair.id_tensor.eval())

  def test_get_sparse_tensors_int32(self):
    column = fc.categorical_column_with_vocabulary_file(
        key='aaa',
        vocabulary_file=self._warriors_vocabulary_file_name,
        vocabulary_size=self._warriors_vocabulary_size,
        dtype=dtypes.int32)
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1), (2, 2)),
        values=(11, 100, 30, 22),
        dense_shape=(3, 3))
    # pylint: disable=protected-access
    id_weight_pair = column._get_sparse_tensors(
        fc._LazyBuilder({'aaa': inputs}))
    # pylint: enable=protected-access
    self.assertIsNone(id_weight_pair.weight_tensor)
    with _initialized_session():
      _assert_sparse_tensor_value(
          self,
          sparse_tensor.SparseTensorValue(
              indices=inputs.indices,
              values=np.array((2, -1, 0, 4), dtype=np.int64),
              dense_shape=inputs.dense_shape),
          id_weight_pair.id_tensor.eval())

  def test_get_sparse_tensors_int32_dense_input(self):
    default_value = -100
    column = fc.categorical_column_with_vocabulary_file(
        key='aaa',
        vocabulary_file=self._warriors_vocabulary_file_name,
        vocabulary_size=self._warriors_vocabulary_size,
        dtype=dtypes.int32,
        default_value=default_value)
    # pylint: disable=protected-access
    id_weight_pair = column._get_sparse_tensors(fc._LazyBuilder({
        'aaa': ((11, -1, -1), (100, 30, -1), (-1, -1, 22))
    }))
    # pylint: enable=protected-access
    self.assertIsNone(id_weight_pair.weight_tensor)
    with _initialized_session():
      _assert_sparse_tensor_value(
          self,
          sparse_tensor.SparseTensorValue(
              indices=((0, 0), (1, 0), (1, 1), (2, 2)),
              values=np.array((2, default_value, 0, 4), dtype=np.int64),
              dense_shape=(3, 3)),
          id_weight_pair.id_tensor.eval())

  def test_get_sparse_tensors_int32_with_oov_buckets(self):
    column = fc.categorical_column_with_vocabulary_file(
        key='aaa',
        vocabulary_file=self._warriors_vocabulary_file_name,
        vocabulary_size=self._warriors_vocabulary_size,
        dtype=dtypes.int32,
        num_oov_buckets=100)
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1), (2, 2)),
        values=(11, 100, 30, 22),
        dense_shape=(3, 3))
    # pylint: disable=protected-access
    id_weight_pair = column._get_sparse_tensors(
        fc._LazyBuilder({'aaa': inputs}))
    # pylint: enable=protected-access
    self.assertIsNone(id_weight_pair.weight_tensor)
    with _initialized_session():
      _assert_sparse_tensor_value(
          self,
          sparse_tensor.SparseTensorValue(
              indices=inputs.indices,
              values=np.array((2, 60, 0, 4), dtype=np.int64),
              dense_shape=inputs.dense_shape),
          id_weight_pair.id_tensor.eval())

  def test_make_linear_model(self):
    wire_column = fc.categorical_column_with_vocabulary_file(
        key='wire',
        vocabulary_file=self._wire_vocabulary_file_name,
        vocabulary_size=self._wire_vocabulary_size,
        num_oov_buckets=1)
    self.assertEqual(4, wire_column._num_buckets)
    with ops.Graph().as_default():
      predictions = fc.make_linear_model({
          wire_column.name: sparse_tensor.SparseTensorValue(
              indices=((0, 0), (1, 0), (1, 1)),
              values=('marlo', 'skywalker', 'omar'),
              dense_shape=(2, 2))
      }, (wire_column,))
      bias = get_linear_model_bias()
      wire_var = get_linear_model_column_var(wire_column)
      with _initialized_session():
        self.assertAllClose((0.,), bias.eval())
        self.assertAllClose(((0.,), (0.,), (0.,), (0.,)), wire_var.eval())
        self.assertAllClose(((0.,), (0.,)), predictions.eval())
        wire_var.assign(((1.,), (2.,), (3.,), (4.,))).eval()
        # 'marlo' -> 2: wire_var[2] = 3
        # 'skywalker' -> 3, 'omar' -> 0: wire_var[3] + wire_var[0] = 4+1 = 5
        self.assertAllClose(((3.,), (5.,)), predictions.eval())


class VocabularyListCategoricalColumnTest(test.TestCase):

  def test_defaults_string(self):
    column = fc.categorical_column_with_vocabulary_list(
        key='aaa', vocabulary_list=('omar', 'stringer', 'marlo'))
    self.assertEqual('aaa', column.name)
    # pylint: disable=protected-access
    self.assertEqual(3, column._num_buckets)
    self.assertEqual({
        'aaa': parsing_ops.VarLenFeature(dtypes.string)
    }, column._parse_example_config)
    # pylint: enable=protected-access

  def test_defaults_int(self):
    column = fc.categorical_column_with_vocabulary_list(
        key='aaa', vocabulary_list=(12, 24, 36))
    self.assertEqual('aaa', column.name)
    # pylint: disable=protected-access
    self.assertEqual(3, column._num_buckets)
    self.assertEqual({
        'aaa': parsing_ops.VarLenFeature(dtypes.int64)
    }, column._parse_example_config)
    # pylint: enable=protected-access

  def test_all_constructor_args(self):
    column = fc.categorical_column_with_vocabulary_list(
        key='aaa', vocabulary_list=(12, 24, 36), dtype=dtypes.int32,
        default_value=-99)
    # pylint: disable=protected-access
    self.assertEqual(3, column._num_buckets)
    self.assertEqual({
        'aaa': parsing_ops.VarLenFeature(dtypes.int32)
    }, column._parse_example_config)
    # pylint: enable=protected-access

  def test_deep_copy(self):
    """Tests deepcopy of categorical_column_with_hash_bucket."""
    original = fc.categorical_column_with_vocabulary_list(
        key='aaa', vocabulary_list=(12, 24, 36), dtype=dtypes.int32)
    for column in (original, copy.deepcopy(original)):
      self.assertEqual('aaa', column.name)
      # pylint: disable=protected-access
      self.assertEqual(3, column._num_buckets)
      self.assertEqual({
          'aaa': parsing_ops.VarLenFeature(dtypes.int32)
      }, column._parse_example_config)
      # pylint: enable=protected-access

  def test_invalid_dtype(self):
    with self.assertRaisesRegexp(ValueError, 'dtype must be string or integer'):
      fc.categorical_column_with_vocabulary_list(
          key='aaa', vocabulary_list=('omar', 'stringer', 'marlo'),
          dtype=dtypes.float32)

  def test_invalid_mapping_dtype(self):
    with self.assertRaisesRegexp(
        ValueError, r'vocabulary dtype must be string or integer'):
      fc.categorical_column_with_vocabulary_list(
          key='aaa', vocabulary_list=(12., 24., 36.))

  def test_mismatched_int_dtype(self):
    with self.assertRaisesRegexp(
        ValueError, r'dtype.*and vocabulary dtype.*do not match'):
      fc.categorical_column_with_vocabulary_list(
          key='aaa', vocabulary_list=('omar', 'stringer', 'marlo'),
          dtype=dtypes.int32)

  def test_mismatched_string_dtype(self):
    with self.assertRaisesRegexp(
        ValueError, r'dtype.*and vocabulary dtype.*do not match'):
      fc.categorical_column_with_vocabulary_list(
          key='aaa', vocabulary_list=(12, 24, 36), dtype=dtypes.string)

  def test_none_mapping(self):
    with self.assertRaisesRegexp(
        ValueError, r'vocabulary_list.*must be non-empty'):
      fc.categorical_column_with_vocabulary_list(
          key='aaa', vocabulary_list=None)

  def test_empty_mapping(self):
    with self.assertRaisesRegexp(
        ValueError, r'vocabulary_list.*must be non-empty'):
      fc.categorical_column_with_vocabulary_list(
          key='aaa', vocabulary_list=tuple([]))

  def test_duplicate_mapping(self):
    with self.assertRaisesRegexp(ValueError, 'Duplicate keys'):
      fc.categorical_column_with_vocabulary_list(
          key='aaa', vocabulary_list=(12, 24, 12))

  def test_invalid_input_dtype_int32(self):
    column = fc.categorical_column_with_vocabulary_list(
        key='aaa',
        vocabulary_list=('omar', 'stringer', 'marlo'))
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1)),
        values=(12, 24, 36),
        dense_shape=(2, 2))
    with self.assertRaisesRegexp(ValueError, 'dtype must be compatible'):
      # pylint: disable=protected-access
      column._get_sparse_tensors(fc._LazyBuilder({'aaa': inputs}))
      # pylint: enable=protected-access

  def test_invalid_input_dtype_string(self):
    column = fc.categorical_column_with_vocabulary_list(
        key='aaa',
        vocabulary_list=(12, 24, 36))
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1)),
        values=('omar', 'stringer', 'marlo'),
        dense_shape=(2, 2))
    with self.assertRaisesRegexp(ValueError, 'dtype must be compatible'):
      # pylint: disable=protected-access
      column._get_sparse_tensors(fc._LazyBuilder({'aaa': inputs}))
      # pylint: enable=protected-access

  def test_get_sparse_tensors(self):
    column = fc.categorical_column_with_vocabulary_list(
        key='aaa',
        vocabulary_list=('omar', 'stringer', 'marlo'))
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1)),
        values=('marlo', 'skywalker', 'omar'),
        dense_shape=(2, 2))
    # pylint: disable=protected-access
    id_weight_pair = column._get_sparse_tensors(
        fc._LazyBuilder({'aaa': inputs}))
    # pylint: enable=protected-access
    self.assertIsNone(id_weight_pair.weight_tensor)
    with _initialized_session():
      _assert_sparse_tensor_value(
          self,
          sparse_tensor.SparseTensorValue(
              indices=inputs.indices,
              values=np.array((2, -1, 0), dtype=np.int64),
              dense_shape=inputs.dense_shape),
          id_weight_pair.id_tensor.eval())

  def test_get_sparse_tensors_dense_input(self):
    column = fc.categorical_column_with_vocabulary_list(
        key='aaa',
        vocabulary_list=('omar', 'stringer', 'marlo'))
    # pylint: disable=protected-access
    id_weight_pair = column._get_sparse_tensors(fc._LazyBuilder({
        'aaa': (('marlo', ''), ('skywalker', 'omar'))
    }))
    # pylint: enable=protected-access
    self.assertIsNone(id_weight_pair.weight_tensor)
    with _initialized_session():
      _assert_sparse_tensor_value(
          self,
          sparse_tensor.SparseTensorValue(
              indices=((0, 0), (1, 0), (1, 1)),
              values=np.array((2, -1, 0), dtype=np.int64),
              dense_shape=(2, 2)),
          id_weight_pair.id_tensor.eval())

  def test_get_sparse_tensors_default_value_in_vocabulary(self):
    column = fc.categorical_column_with_vocabulary_list(
        key='aaa',
        vocabulary_list=('omar', 'stringer', 'marlo'),
        default_value=2)
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1)),
        values=('marlo', 'skywalker', 'omar'),
        dense_shape=(2, 2))
    # pylint: disable=protected-access
    id_weight_pair = column._get_sparse_tensors(
        fc._LazyBuilder({'aaa': inputs}))
    # pylint: enable=protected-access
    self.assertIsNone(id_weight_pair.weight_tensor)
    with _initialized_session():
      _assert_sparse_tensor_value(
          self,
          sparse_tensor.SparseTensorValue(
              indices=inputs.indices,
              values=np.array((2, 2, 0), dtype=np.int64),
              dense_shape=inputs.dense_shape),
          id_weight_pair.id_tensor.eval())

  def test_get_sparse_tensors_int32(self):
    column = fc.categorical_column_with_vocabulary_list(
        key='aaa',
        vocabulary_list=np.array((30, 35, 11, 23, 22), dtype=np.int32),
        dtype=dtypes.int32)
    inputs = sparse_tensor.SparseTensorValue(
        indices=((0, 0), (1, 0), (1, 1), (2, 2)),
        values=np.array((11, 100, 30, 22), dtype=np.int32),
        dense_shape=(3, 3))
    # pylint: disable=protected-access
    id_weight_pair = column._get_sparse_tensors(
        fc._LazyBuilder({'aaa': inputs}))
    # pylint: enable=protected-access
    self.assertIsNone(id_weight_pair.weight_tensor)
    with _initialized_session():
      _assert_sparse_tensor_value(
          self,
          sparse_tensor.SparseTensorValue(
              indices=inputs.indices,
              values=np.array((2, -1, 0, 4), dtype=np.int64),
              dense_shape=inputs.dense_shape),
          id_weight_pair.id_tensor.eval())

  def test_get_sparse_tensors_int32_dense_input(self):
    default_value = -100
    column = fc.categorical_column_with_vocabulary_list(
        key='aaa',
        vocabulary_list=np.array((30, 35, 11, 23, 22), dtype=np.int32),
        dtype=dtypes.int32,
        default_value=default_value)
    # pylint: disable=protected-access
    id_weight_pair = column._get_sparse_tensors(fc._LazyBuilder({
        'aaa': np.array(
            ((11, -1, -1), (100, 30, -1), (-1, -1, 22)),
            dtype=np.int32)
    }))
    # pylint: enable=protected-access
    self.assertIsNone(id_weight_pair.weight_tensor)
    with _initialized_session():
      _assert_sparse_tensor_value(
          self,
          sparse_tensor.SparseTensorValue(
              indices=((0, 0), (1, 0), (1, 1), (2, 2)),
              values=np.array((2, default_value, 0, 4), dtype=np.int64),
              dense_shape=(3, 3)),
          id_weight_pair.id_tensor.eval())

  def test_make_linear_model(self):
    wire_column = fc.categorical_column_with_vocabulary_list(
        key='aaa',
        vocabulary_list=('omar', 'stringer', 'marlo'))
    self.assertEqual(3, wire_column._num_buckets)
    with ops.Graph().as_default():
      predictions = fc.make_linear_model({
          wire_column.name: sparse_tensor.SparseTensorValue(
              indices=((0, 0), (1, 0), (1, 1)),
              values=('marlo', 'skywalker', 'omar'),
              dense_shape=(2, 2))
      }, (wire_column,))
      bias = get_linear_model_bias()
      wire_var = get_linear_model_column_var(wire_column)
      with _initialized_session():
        self.assertAllClose((0.,), bias.eval())
        self.assertAllClose(((0.,), (0.,), (0.,)), wire_var.eval())
        self.assertAllClose(((0.,), (0.,)), predictions.eval())
        wire_var.assign(((1.,), (2.,), (3.,))).eval()
        # 'marlo' -> 2: wire_var[2] = 3
        # 'skywalker' -> None, 'omar' -> 0: wire_var[0] = 1
        self.assertAllClose(((3.,), (1.,)), predictions.eval())


if __name__ == '__main__':
  test.main()
