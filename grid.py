#!/usr/bin/env python
import sys
import numpy as np
import tensorflow as tf
from input_velodyne import *
import glob

def batch_norm(inputs, is_training, decay=0.9, eps=1e-5):
    """Batch Normalization

       Args:
           inputs: input data(Batch size) from last layer
           is_training: when you test, please set is_training "None"
       Returns:
           output for next layer
    """
    gamma = tf.Variable(tf.ones(inputs.get_shape()[1:]), name="gamma")
    beta = tf.Variable(tf.zeros(inputs.get_shape()[1:]), name="beta")
    pop_mean = tf.Variable(tf.zeros(inputs.get_shape()[1:]), trainable=False, name="pop_mean")
    pop_var = tf.Variable(tf.ones(inputs.get_shape()[1:]), trainable=False, name="pop_var")


    def is_true():
        batch_mean, batch_var = tf.nn.moments(inputs, [0])
        train_mean = tf.assign(pop_mean, pop_mean * decay + batch_mean*(1 - decay))
        train_var = tf.assign(pop_var, pop_var * decay + batch_var * (1 - decay))
        with tf.control_dependencies([train_mean, train_var]):
            return pop_mean, pop_var
            # return tf.nn.batch_normalization(inputs, batch_mean, batch_var, beta, gamma, eps)

    def is_false():
        return pop_mean, pop_var
        # return tf.nn.batch_normalization(inputs, pop_mean, pop_var, beta, gamma, eps)

    mean, var = tf.cond(is_training, is_true, is_false)
    normed = tf.nn.batch_normalization(inputs, mean, var, beta, gamma, eps)
    # normed = tf.cond(is_training, is_true, is_false)
    return normed

def conv3DLayer(input_layer, input_dim, output_dim, height, width, length, stride, activation=tf.nn.relu, padding="SAME", name="", is_training=True):
    #[batch, 32, 32, 32, channel]
    with tf.variable_scope("conv3D" + name) as c3:
        kernel = tf.get_variable("weights", shape=[length, height, width, input_dim, output_dim], \
            dtype=tf.float32, initializer=tf.truncated_normal_initializer(stddev=0.1))
        b = tf.get_variable("bias", shape=[output_dim], dtype=tf.float32, initializer=tf.constant_initializer(0.0))
        conv = tf.nn.conv3d(input_layer, kernel, stride, padding=padding)
        bias = tf.nn.bias_add(conv, b)
        if activation:
            bias = activation(bias, name="activation")
        # bias = tf.contrib.layers.batch_norm(bias, data_format='NHWC', center=True, scale=True, is_training=is_training, scope="norm")
        # bias = batch_norm(bias, is_training)
    return bias

def conv3D_to_output(input_layer, input_dim, output_dim, height, width, length, stride, activation=tf.nn.relu, padding="SAME", name=""):
    #[batch, 32, 32, 32, channel]
    with tf.variable_scope("conv3D" + name):
        kernel = tf.get_variable("weights", shape=[length, height, width, input_dim, output_dim], \
            dtype=tf.float32, initializer=tf.constant_initializer(0.01))
        conv = tf.nn.conv3d(input_layer, kernel, stride, padding=padding)
    return conv

def deconv3D_to_output(input_layer, input_dim, output_dim, height, width, length, stride, output_shape, activation=tf.nn.relu, padding="SAME", name=""):
    with tf.variable_scope("deconv3D"+name):
        kernel = tf.get_variable("weights", shape=[length, height, width, output_dim, input_dim], \
            dtype=tf.float32, initializer=tf.constant_initializer(0.01))
        deconv = tf.nn.conv3d_transpose(input_layer, kernel, output_shape, stride, padding="SAME")
    return deconv

def fully_connected(input_layer, shape, name="", is_training=True):
    with tf.variable_scope("fully" + name):
        kernel = tf.get_variable("weights", shape=shape, \
            dtype=tf.float32, initializer=tf.truncated_normal_initializer(stddev=0.01))
        fully = tf.matmul(input_layer, kernel)
        fully = tf.nn.relu(fully)
        fully = batch_norm(fully, is_training)
        return fully

class BNBLayer(object):
    def __init__(self):
        pass

    def build_graph(self, voxel, activation=tf.nn.relu, is_training=True):
        self.layer1 = conv3DLayer(voxel, 1, 10, 5, 5, 5, [1, 2, 2, 2, 1], name="layer1", activation=activation, is_training=is_training)
        self.layer2 = conv3DLayer(self.layer1, 10, 20, 5, 5, 5, [1, 2, 2, 2, 1], name="layer2", activation=activation, is_training=is_training)
        self.layer3 = conv3DLayer(self.layer2, 20, 30, 3, 3, 3, [1, 2, 2, 2, 1], name="layer3", activation=activation, is_training=is_training)
        base_shape = self.layer2.get_shape().as_list()
        obj_output_shape = [tf.shape(self.layer3)[0], base_shape[1], base_shape[2], base_shape[3], 2]
        cord_output_shape = [tf.shape(self.layer3)[0], base_shape[1], base_shape[2], base_shape[3], 24]
        self.objectness = deconv3D_to_output(self.layer3, 30, 2, 3, 3, 3, [1, 2, 2, 2, 1], obj_output_shape, name="objectness", activation=None)
        self.cordinate = deconv3D_to_output(self.layer3, 30, 24, 3, 3, 3, [1, 2, 2, 2, 1], cord_output_shape, name="cordinate", activation=None)
        self.y = tf.nn.softmax(self.objectness, dim=-1)

def ssd_model(sess, voxel_shape=(300, 300, 300),activation=tf.nn.relu):
    voxel = tf.placeholder(tf.float32, [None, voxel_shape[0], voxel_shape[1], voxel_shape[2], 1])
    phase_train = tf.placeholder(tf.bool, name='phase_train')
    with tf.variable_scope("3D_CNN_model") as scope:
        bnb_model = BNBLayer()
        bnb_model.build_graph(voxel, activation=activation, is_training=phase_train)

    initialized_var = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope="3D_CNN_model")
    sess.run(tf.variables_initializer(initialized_var))
    return bnb_model, voxel, phase_train

def ssd_test_model(sess, voxel_shape=(300, 300, 300),activation=tf.nn.relu):
    voxel = tf.placeholder(tf.float32, [None, voxel_shape[0], voxel_shape[1], voxel_shape[2], 1])
    phase_train = tf.placeholder(tf.bool, name='phase_train')
    with tf.variable_scope("3D_CNN_model") as scope:
        bnb_model = BNBLayer()
        bnb_model.build_graph(voxel, activation=activation, is_training=phase_train)

    initialized_var = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope="3D_CNN_model")
    sess.run(tf.variables_initializer(initialized_var))
    return bnb_model, voxel, phase_train

def loss_func(model):
    g_map = tf.placeholder(tf.float32, model.cordinate.get_shape().as_list()[:4])
    g_cord = tf.placeholder(tf.float32, model.cordinate.get_shape().as_list())
    object_loss = tf.multiply(g_map, model.objectness[:, :, :, :, 0])
    non_gmap = tf.subtract(tf.ones_like(g_map, dtype=tf.float32), g_map)
    nonobject_loss = tf.multiply(non_gmap, model.objectness[:, :, :, :, 1])
    # sum_object_loss = tf.add(tf.exp(object_loss), tf.exp(nonobject_loss))
    sum_object_loss = tf.exp(-tf.add(object_loss, nonobject_loss))
    # sum_object_loss = tf.exp(-nonobject_loss)
    bunbo = tf.add(tf.exp(-model.objectness[:, :, :, :, 0]), tf.exp(-model.objectness[:, :, :, :, 1]))
    obj_loss = 0.005 * tf.reduce_sum(-tf.log(tf.div(sum_object_loss, bunbo)))

    cord_diff = tf.multiply(g_map, tf.reduce_sum(tf.square(tf.subtract(model.cordinate, g_cord)), 4))
    cord_loss = tf.reduce_sum(cord_diff)
    return obj_loss, obj_loss, cord_loss, g_map, g_cord

def loss_func2(model):
    g_map = tf.placeholder(tf.float32, model.cordinate.get_shape().as_list()[:4])
    obj_loss = tf.reduce_sum(tf.square(tf.subtract(model.objectness[:, :, :, :, 0], g_map)))

    g_cord = tf.placeholder(tf.float32, model.cordinate.get_shape().as_list())
    cord_diff = tf.multiply(g_map, tf.reduce_sum(tf.square(tf.subtract(model.cordinate, g_cord)), 4))
    cord_loss = tf.reduce_sum(cord_diff) * 0.1
    return tf.add(obj_loss, cord_loss), g_map, g_cord

def loss_func3(model):
    g_map = tf.placeholder(tf.float32, model.cordinate.get_shape().as_list()[:4])
    g_cord = tf.placeholder(tf.float32, model.cordinate.get_shape().as_list())
    non_gmap = tf.subtract(tf.ones_like(g_map, dtype=tf.float32), g_map)

    elosion = 0.00001
    y = model.y
    is_obj_loss = -tf.reduce_sum(tf.multiply(g_map,  tf.log(y[:, :, :, :, 0] + elosion)))
    non_obj_loss = tf.multiply(-tf.reduce_sum(tf.multiply(non_gmap, tf.log(y[:, :, :, :, 1] + elosion))), 0.0008)
    cross_entropy = tf.add(is_obj_loss, non_obj_loss)
    obj_loss = cross_entropy

    g_cord = tf.placeholder(tf.float32, model.cordinate.get_shape().as_list())
    cord_diff = tf.multiply(g_map, tf.reduce_sum(tf.square(tf.subtract(model.cordinate, g_cord)), 4))
    cord_loss = tf.multiply(tf.reduce_sum(cord_diff), 0.02)
    return tf.add(obj_loss, cord_loss), obj_loss, cord_loss, is_obj_loss, non_obj_loss, g_map, g_cord, y

def create_optimizer(all_loss, lr=0.001):
    opt = tf.train.AdamOptimizer(lr)
    optimizer = opt.minimize(all_loss)
    return optimizer

def train(batch_num, velodyne_path, label_path=None, calib_path=None, resolution=0.2, dataformat="pcd", label_type="txt", is_velo_cam=False):
    # tf Graph input
    batch_size = batch_num
    training_epochs = 101

    with tf.Session() as sess:
        model, voxel, phase_train = ssd_model(sess, voxel_shape=(360, 400, 40), activation=tf.nn.relu)
        saver = tf.train.Saver()
        total_loss, obj_loss, cord_loss, is_obj_loss, non_obj_loss, g_map, g_cord, y = loss_func3(model)
        optimizer = create_optimizer(total_loss, lr=0.01)
        init = tf.global_variables_initializer()
        sess.run(init)

        for epoch in range(training_epochs):
            for (batch_x, batch_g_map, batch_g_cord) in lidar_generator(batch_num, velodyne_path, label_path=label_path, \
               calib_path=calib_path,resolution=resolution, dataformat=dataformat, label_type=label_type, is_velo_cam=is_velo_cam):
                # print batch_x.shape, batch_g_map.shape, batch_g_cord.shape, batch_num
                sess.run(optimizer, feed_dict={voxel: batch_x, g_map: batch_g_map, g_cord: batch_g_cord, phase_train:True})

                # ct = sess.run(total_loss, feed_dict={voxel: batch_x, g_map: batch_g_map, g_cord: batch_g_cord, phase_train:True})
                # co = sess.run(obj_loss, feed_dict={voxel: batch_x, g_map: batch_g_map, g_cord: batch_g_cord, phase_train:True})
                cc = sess.run(cord_loss, feed_dict={voxel: batch_x, g_map: batch_g_map, g_cord: batch_g_cord, phase_train:True})
                iol = sess.run(is_obj_loss, feed_dict={voxel: batch_x, g_map: batch_g_map, g_cord: batch_g_cord, phase_train:True})
                nol = sess.run(non_obj_loss, feed_dict={voxel: batch_x, g_map: batch_g_map, g_cord: batch_g_cord, phase_train:True})
                # soft = sess.run(y, feed_dict={voxel: batch_x, g_map: batch_g_map, g_cord: batch_g_cord})
                # print soft[0, 0, 0, 0, :]
                # print("Epoch:", '%04d' % (epoch+1), "cost=", "{:.9f}".format(ct))
                # print("Epoch:", '%04d' % (epoch+1), "cost=", "{:.9f}".format(co))
                print("Epoch:", '%04d' % (epoch+1), "cost=", "{:.9f}".format(cc))
                print("Epoch:", '%04d' % (epoch+1), "cost=", "{:.9f}".format(iol))
                print("Epoch:", '%04d' % (epoch+1), "cost=", "{:.9f}".format(nol))
                # print ""

            if (epoch != 0) and (epoch % 10 == 0):
                print "Save epoch " + str(epoch)
                saver.save(sess, "velodyne_10th_try_" + str(epoch) + ".ckpt")
        print("Optimization Finished!")

def test(batch_num, velodyne_path, label_path=None, calib_path=None, resolution=0.2, dataformat="pcd", label_type="txt", is_velo_cam=False):
    # tf Graph input
    batch_size = batch_num # 1
    training_epochs = 5
    p = []
    pc = None
    bounding_boxes = None
    places = None
    rotates = None
    size = None
    proj_velo = None

    if dataformat == "bin":
        pc = load_pc_from_bin(velodyne_path)
    elif dataformat == "pcd":
        pc = load_pc_from_pcd(velodyne_path)

    if calib_path:
        calib = read_calib_file(calib_path)
        proj_velo = proj_to_velo(calib)[:, :3]

    if label_path:
        places, rotates, size = read_labels(label_path, label_type, calib_path=calib_path, is_velo_cam=is_velo_cam, proj_velo=proj_velo)

    corners = get_boxcorners(places, rotates, size)
    filter_car_data(corners)
    pc = filter_camera_angle(pc)

    voxel =  raw_to_voxel(pc, resolution=resolution)
    center_sphere = center_to_sphere(places, size, resolution=resolution)
    corner_label = corner_to_train(corners, center_sphere, resolution=resolution)
    g_map = create_objectness_label(center_sphere, resolution=resolution)
    g_cord = corner_label.reshape(corner_label.shape[0], -1)

    voxel_x = voxel.reshape(1, voxel.shape[0], voxel.shape[1], voxel.shape[2], 1)

    with tf.Session() as sess:
        model, voxel, phase_train = ssd_test_model(sess, voxel_shape=(360, 400, 40), activation=tf.nn.relu)
        # optimizer = create_optimizer(total_loss)
        saver = tf.train.Saver()
        new_saver = tf.train.import_meta_graph("velodyne_10th_try_100.ckpt.meta")
        # last_model = tf.train.latest_checkpoint('./velodyne_10th_try_100.ckpt')
        last_model = "./velodyne_10th_try_90.ckpt"
        print last_model
        # total_loss, g_map, g_cord = loss_func(model)

        saver.restore(sess, last_model)

        objectness = model.objectness
        cordinate = model.cordinate
        y = model.y

        objectness = sess.run(objectness, feed_dict={voxel: voxel_x, phase_train:False})[0, :, :, :, 0]
        cordinate = sess.run(cordinate, feed_dict={voxel: voxel_x, phase_train:False})[0]
        y = sess.run(y, feed_dict={voxel: voxel_x, phase_train:False})[0, :, :, :, 0]
        print objectness.shape, objectness.max(), objectness.min()
        print y.shape, y.max(), y.min()

        # print np.where(objectness >= 0.55)
        index = np.where(y >= 0.995)
        print np.vstack((index[0], np.vstack((index[1], index[2])))).transpose()
        print np.vstack((index[0], np.vstack((index[1], index[2])))).transpose().shape

        a = center_to_sphere(places, size, resolution=0.25)
        print a[a[:, 0].argsort()]
        # center = np.array([20, 57, 3])
        #
        # pred_center = sphere_to_center(center, resolution=resolution)
        # print pred_center
        # print cordinate.shape
        # corners = cordinate[center[0], center[1], center[2]].reshape(-1, 3)
        centers = np.vstack((index[0], np.vstack((index[1], index[2])))).transpose()
        centers = sphere_to_center(centers, resolution=0.25)
        corners = cordinate[index].reshape(-1, 8, 3) + centers[:, np.newaxis]
        print corners.shape
        publish_pc2(pc, corners.reshape(-1, 3))
        # pred_corners = corners + pred_center
        # print pred_corners

def lidar_generator(batch_num, velodyne_path, label_path=None, calib_path=None, resolution=0.2, dataformat="pcd", label_type="txt", is_velo_cam=False):
    velodynes_path = glob.glob(velodyne_path)
    labels_path = glob.glob(label_path)
    calibs_path = glob.glob(calib_path)
    velodynes_path.sort()
    labels_path.sort()
    calibs_path.sort()
    iter_num = len(velodynes_path) // batch_num

    for itn in range(iter_num):
        batch_voxel = []
        batch_g_map = []
        batch_g_cord = []

        for velodynes, labels, calibs in zip(velodynes_path[itn*batch_num:(itn+1)*batch_num], \
            labels_path[itn*batch_num:(itn+1)*batch_num], calibs_path[itn*batch_num:(itn+1)*batch_num]):
            p = []
            pc = None
            bounding_boxes = None
            places = None
            rotates = None
            size = None
            proj_velo = None

            if dataformat == "bin":
                pc = load_pc_from_bin(velodynes)
            elif dataformat == "pcd":
                pc = load_pc_from_pcd(velodynes)

            if calib_path:
                calib = read_calib_file(calibs)
                proj_velo = proj_to_velo(calib)[:, :3]

            if label_path:
                places, rotates, size = read_labels(labels, label_type, calib_path=calib_path, is_velo_cam=is_velo_cam, proj_velo=proj_velo)
                if places is None:
                    continue

            corners = get_boxcorners(places, rotates, size)
            filter_car_data(corners)
            pc = filter_camera_angle(pc)

            voxel =  raw_to_voxel(pc, resolution=resolution)
            center_sphere = center_to_sphere(places, size, resolution=resolution)
            corner_label = corner_to_train(corners, center_sphere, resolution=resolution)
            g_map = create_objectness_label(center_sphere, resolution=resolution)
            g_cord = corner_label.reshape(corner_label.shape[0], -1)
            g_cord = corner_to_voxel(voxel.shape, g_cord, center_sphere)

            batch_voxel.append(voxel)
            batch_g_map.append(g_map)
            batch_g_cord.append(g_cord)
        yield np.array(batch_voxel, dtype=np.float32)[:, :, :, :, np.newaxis], np.array(batch_g_map, dtype=np.float32), np.array(batch_g_cord, dtype=np.float32)


if __name__ == '__main__':
    # pcd_path = "../data/training/velodyne/*.bin"
    # label_path = "../data/training/label_2/*.txt"
    # calib_path = "../data/training/calib/*.txt"
    # train(20, pcd_path, label_path=label_path, resolution=0.25, calib_path=calib_path, dataformat="bin", is_velo_cam=True)
    #
    pcd_path = "../data/training/velodyne/006000.bin"
    label_path = "../data/training/label_2/006000.txt"
    calib_path = "../data/training/calib/006000.txt"
    test(1, pcd_path, label_path=label_path, resolution=0.25, calib_path=calib_path, dataformat="bin", is_velo_cam=True)
