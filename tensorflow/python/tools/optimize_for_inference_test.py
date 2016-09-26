# pylint: disable=g-bad-file-header
# Copyright 2015 The TensorFlow Authors. All Rights Reserved.
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

"""Tests for tensorflow.python.client.graph_util."""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np
import tensorflow as tf

from tensorflow.python.framework import tensor_util
from tensorflow.python.ops import gen_nn_ops
from tensorflow.python.ops import math_ops  # pylint: disable=unused-import
from tensorflow.python.tools import optimize_for_inference_lib


class OptimizeForInferenceTest(tf.test.TestCase):

  def create_node_def(self, op, name, inputs):
    new_node = tf.NodeDef()
    new_node.op = op
    new_node.name = name
    for input_name in inputs:
      new_node.input.extend([input_name])
    return new_node

  def create_constant_node_def(self, name, value, dtype, shape=None):
    node = self.create_node_def("Const", name, [])
    self.set_attr_dtype(node, "dtype", dtype)
    self.set_attr_tensor(node, "value", value, dtype, shape)
    return node

  def set_attr_dtype(self, node, key, value):
    node.attr[key].CopyFrom(tf.AttrValue(type=value.as_datatype_enum))

  def set_attr_tensor(self, node, key, value, dtype, shape=None):
    node.attr[key].CopyFrom(tf.AttrValue(
        tensor=tensor_util.make_tensor_proto(value,
                                             dtype=dtype,
                                             shape=shape)))

  def testOptimizeForInference(self):
    unused_constant_name = "unused_constant"
    unconnected_add_name = "unconnected_add"
    a_constant_name = "a_constant"
    b_constant_name = "b_constant"
    a_check_name = "a_check"
    b_check_name = "b_check"
    a_identity_name = "a_identity"
    b_identity_name = "b_identity"
    add_name = "add"
    unused_output_add_name = "unused_output_add"
    graph_def = tf.GraphDef()
    unused_constant = self.create_constant_node_def(unused_constant_name,
                                                    value=0,
                                                    dtype=tf.float32,
                                                    shape=[])
    graph_def.node.extend([unused_constant])
    unconnected_add_node = self.create_node_def("Add", unconnected_add_name,
                                                [unused_constant_name,
                                                 unused_constant_name])
    self.set_attr_dtype(unconnected_add_node, "T", tf.float32)
    graph_def.node.extend([unconnected_add_node])
    a_constant = self.create_constant_node_def(a_constant_name,
                                               value=1,
                                               dtype=tf.float32,
                                               shape=[])
    graph_def.node.extend([a_constant])
    a_check_node = self.create_node_def("CheckNumerics", a_check_name,
                                        [a_constant_name])
    graph_def.node.extend([a_check_node])
    a_identity_node = self.create_node_def("Identity", a_identity_name,
                                           [a_constant_name,
                                            "^" + a_check_name])
    graph_def.node.extend([a_identity_node])
    b_constant = self.create_constant_node_def(b_constant_name,
                                               value=1,
                                               dtype=tf.float32,
                                               shape=[])
    graph_def.node.extend([b_constant])
    b_check_node = self.create_node_def("CheckNumerics", b_check_name,
                                        [b_constant_name])
    graph_def.node.extend([b_check_node])
    b_identity_node = self.create_node_def("Identity", b_identity_name,
                                           [b_constant_name,
                                            "^" + b_check_name])
    graph_def.node.extend([b_identity_node])
    add_node = self.create_node_def("Add", add_name,
                                    [a_identity_name,
                                     b_identity_name])
    self.set_attr_dtype(add_node, "T", tf.float32)
    graph_def.node.extend([add_node])
    unused_output_add_node = self.create_node_def("Add", unused_output_add_name,
                                                  [add_name, b_constant_name])
    self.set_attr_dtype(unused_output_add_node, "T", tf.float32)
    graph_def.node.extend([unused_output_add_node])

    expected_output = tf.GraphDef()
    a_constant = self.create_constant_node_def(a_constant_name,
                                               value=1,
                                               dtype=tf.float32,
                                               shape=[])
    expected_output.node.extend([a_constant])
    b_constant = self.create_constant_node_def(b_constant_name,
                                               value=1,
                                               dtype=tf.float32,
                                               shape=[])
    expected_output.node.extend([b_constant])
    add_node = self.create_node_def("Add", add_name,
                                    [a_constant_name,
                                     b_constant_name])
    self.set_attr_dtype(add_node, "T", tf.float32)
    expected_output.node.extend([add_node])

    output = optimize_for_inference_lib.optimize_for_inference(
        graph_def, [], [add_name], tf.float32.as_datatype_enum)
    self.assertProtoEquals(expected_output, output)

  def testFoldBatchNorms(self):
    with self.test_session() as sess:
      inputs = [1, 4, 2, 5, 3, 6, -1, -4, -2, -5, -3, -6]
      input_op = tf.constant(np.array(inputs), shape=[1, 1, 6, 2],
                             dtype=tf.float32)
      weights = [1, 2, 3, 4, 0.1, 0.2, 0.3, 0.4]
      weights_op = tf.constant(np.array(weights), shape=[1, 2, 2, 2],
                               dtype=tf.float32)
      conv_op = tf.nn.conv2d(input_op, weights_op, [1, 1, 1, 1],
                             padding="SAME", name="conv_op")
      mean_op = tf.constant(np.array([10, 20]), shape=[2], dtype=tf.float32)
      variance_op = tf.constant(np.array([0.25, 0.5]), shape=[2],
                                dtype=tf.float32)
      beta_op = tf.constant(np.array([0.1, 0.6]), shape=[2],
                            dtype=tf.float32)
      gamma_op = tf.constant(np.array([1.0, 2.0]), shape=[2],
                             dtype=tf.float32)
      tf.get_default_graph().graph_def_versions.producer = 8
      gen_nn_ops._batch_norm_with_global_normalization(
          conv_op, mean_op, variance_op, beta_op, gamma_op, 0.00001, False,
          name="output")
      original_graph_def = sess.graph_def
      original_result = sess.run(["output:0"])
    optimized_graph_def = optimize_for_inference_lib.fold_batch_norms(
        original_graph_def)

    with self.test_session() as sess:
      _ = tf.import_graph_def(optimized_graph_def, input_map={},
                              name="optimized")
      optimized_result = sess.run(["optimized/output:0"])

    self.assertAllClose(original_result, optimized_result)

    for node in optimized_graph_def.node:
      self.assertNotEqual("BatchNormWithGlobalNormalization", node.op)

  def testFuseResizePadAndConv(self):
    with self.test_session() as sess:
      inputs = [1, 4, 2, 5, 3, 6, -1, -4, -2, -5, -3, -6]
      input_op = tf.constant(np.array(inputs), shape=[1, 2, 3, 2],
                             dtype=tf.float32)
      resize_op = tf.image.resize_bilinear(input_op, [12, 4],
                                           align_corners=False)
      pad_op = tf.pad(resize_op, [[0, 0], [1, 1], [2, 2], [0, 0]],
                      mode="REFLECT")
      weights = [1, 2, 3, 4, 0.1, 0.2, 0.3, 0.4]
      weights_op = tf.constant(np.array(weights), shape=[1, 2, 2, 2],
                               dtype=tf.float32)
      tf.nn.conv2d(pad_op, weights_op, [1, 1, 1, 1],
                   padding="VALID", name="output")
      original_graph_def = sess.graph_def
      original_result = sess.run(["output:0"])
    optimized_graph_def = optimize_for_inference_lib.fuse_resize_and_conv(
        original_graph_def)

    with self.test_session() as sess:
      _ = tf.import_graph_def(optimized_graph_def, input_map={},
                              name="optimized")
      optimized_result = sess.run(["optimized/output:0"])

    self.assertAllClose(original_result, optimized_result)

    for node in optimized_graph_def.node:
      self.assertNotEqual("Conv2D", node.op)
      self.assertNotEqual("MirrorPad", node.op)
      self.assertNotEqual("ResizeBilinear", node.op)

  def testFuseResizeAndConv(self):
    with self.test_session() as sess:
      inputs = [1, 4, 2, 5, 3, 6, -1, -4, -2, -5, -3, -6]
      input_op = tf.constant(np.array(inputs), shape=[1, 2, 3, 2],
                             dtype=tf.float32)
      resize_op = tf.image.resize_bilinear(input_op, [12, 4],
                                           align_corners=False)
      weights = [1, 2, 3, 4, 0.1, 0.2, 0.3, 0.4]
      weights_op = tf.constant(np.array(weights), shape=[1, 2, 2, 2],
                               dtype=tf.float32)
      tf.nn.conv2d(resize_op, weights_op, [1, 1, 1, 1],
                   padding="VALID", name="output")
      original_graph_def = sess.graph_def
      original_result = sess.run(["output:0"])
    optimized_graph_def = optimize_for_inference_lib.fuse_resize_and_conv(
        original_graph_def)

    with self.test_session() as sess:
      _ = tf.import_graph_def(optimized_graph_def, input_map={},
                              name="optimized")
      optimized_result = sess.run(["optimized/output:0"])

    self.assertAllClose(original_result, optimized_result)

    for node in optimized_graph_def.node:
      self.assertNotEqual("Conv2D", node.op)
      self.assertNotEqual("ResizeBilinear", node.op)


if __name__ == "__main__":
  tf.test.main()
