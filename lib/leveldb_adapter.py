__author__ = 'mbickel'

import numpy as np
import re
import io
import os

import plyvel
import caffe

import imp
ppm_helper = imp.load_source('ppm_helper', os.path.normpath('../lib/ppm_helper.py'))

# test
#import nifti_helper as nh

class Key:
    def __init__(self):
        self.__regex = '(^)(\d){8}_(\d){5}_(seg|img){1}_(xy|xz|yz){1}_(\d){4}_(\d){2}($)'

        self.counter = None
        self.seg_uid = None
        self.type = None
        self.slice_type = None
        self.slice_count = None

        self.slice_mod = None

        self.key = None

    def get_counter(self):
        return self.counter

    def set_counter(self, counter):
        if counter < 0 or counter > 99999999:
            raise ValueError("Counter must be between 0 and 99,999,999")
        self.counter = counter

    def inc_counter(self):
        self.counter += 1
        return self.counter

    def get_seg_uid(self):
        return self.seg_uid

    def set_seg_uid(self, seg_uid):
        if seg_uid < 0 or seg_uid > 99999:
            raise ValueError("Seg_uid must be between 0 and 99,999")
        self.seg_uid = seg_uid

    def get_type(self):
        return self.type

    def set_type(self, type):
        if type == 'seg' or type == 'img':
            self.type = type
        else:
            raise ValueError("Type must be img or seg.")

    def get_slice_type(self):
        return self.slice_type

    def set_slice_type(self, slice_type):
        if slice_type == 'xy' or slice_type == 'xz' or slice_type == 'yz':
            self.slice_type = slice_type
        else:
            raise ValueError("slice_type must be xy, xz or yz")

    def get_slice_count(self):
        return self.slice_count

    def set_slice_count(self, slice_count):
        if slice_count < 0 or slice_count > 9999:
            raise ValueError("Slice_count must be between 0 and 9,999 (" + str(slice_count) + ")")
        self.slice_count = slice_count

    def get_slice_mod(self):
        return self.slice_mod

    def set_slice_mod(self, slice_mod):
        if slice_mod < 0 or slice_mod > 99:
            raise ValueError("Slice_mod must be between 0 and 99")
        self.slice_mod = slice_mod

    def get_key(self):
        self.create_key()
        return self.key

    def set_key(self, key):
        if re.match(self.__regex, key) == None:
            raise ValueError('Wrong key: ' + key)
        else:
            self.key = key

    def create_key(self):
        if self.counter == None or self.seg_uid == None or self.type == None or self.slice_type == None or self.slice_count == None:
            raise ValueError("One of the required values is not set.")
        else:
            self.set_key('%08d_%05d_%s_%s_%04d_%02d' % (self.counter, self.seg_uid, self.type, self.slice_type, self.slice_count, self.slice_mod))

    def disassemble_key(self):
        if self.key == None:
            raise ValueError("Key is not set.")
        else:
            key_parts = self.key.split('_')
            self.counter = int(key_parts[0])
            self.seg_uid = int(key_parts[1])
            self.type = key_parts[2]
            self.slice_type = key_parts[3]
            self.slice_count = int(key_parts[4])
            self.slice_mod = int(key_parts[5])


class ImageAdapter:
    def __init__(self, db_path):
        self.db = plyvel.DB(os.path.normpath(db_path), create_if_missing=True, write_buffer_size=268435456)
        self.wb = None
        self.batch_counter = 0

    def __del__(self):
        self.db.close()

    def add_batch(self, key, ser_img, x_dim, y_dim):
        if self.wb is None:
            self.wb = self.db.write_batch()

        # first create key
        key.create_key()

        # now create datum
        datum = caffe.proto.caffe_pb2.Datum()
        datum.height = y_dim
        datum.width = x_dim
        datum.channels = 1

        datum.data = ser_img

        # add to batch
        self.wb.put(bytes(key.get_key()), bytes(datum.SerializeToString()))

        # auto write
        self.batch_counter += 1
        if self.batch_counter == 1000:
            self.write()

    def add_batch_float(self, key, float_img, x_dim, y_dim):
        if self.wb is None:
            self.wb = self.db.write_batch()

        # first create key
        key.create_key()

        # now create datum
        datum = caffe.proto.caffe_pb2.Datum()
        datum.height = y_dim
        datum.width = x_dim
        datum.channels = 1

        datum.float_data.extend(float_img.flat)

        # add to batch
        self.wb.put(bytes(key.get_key()), bytes(datum.SerializeToString()))

        # auto write
        self.batch_counter += 1
        if self.batch_counter == 1000:
            self.write()

    def write(self):
        if self.wb is None:
            return

        self.wb.write()
        self.wb = None
        self.batch_counter = 0

    @staticmethod
    def datum_to_img(datum):

        try:
            datum_obj = caffe.proto.caffe_pb2.Datum()
            datum_obj.ParseFromString(bytes(datum))

            flat_img = np.fromstring(datum_obj.data, dtype=np.uint8)
            img = flat_img.reshape(datum_obj.height, datum_obj.width)

            return img
        except:
            raise ValueError("Error. String can't be deserialized to datum.")

    def read_img(self, key):
        key.create_key()
        raw_datum = self.db.get(bytes(key.get_key()))

        try:
            datum = caffe.proto.caffe_pb2.Datum()
            datum.ParseFromString(raw_datum)

            flat_img = np.fromstring(datum.data, dtype=np.uint8)
            img = flat_img.reshape(datum.height, datum.width)

            return img
        except:
            raise ValueError('Error. No datum blob at key: ' + str(key.get_key))

    def dump_img(self, key, path):
        img = self.read_img(key)
        ppm_helper.PPM.write(img, path, key.get_key())

    def read_volume(self, key, mod=0):
        slices = {}
        stack = []
        vol = None
        w_key = Key()

        # w_key = Key()
        # found_key = Key()
        #
        # key.disassemble_key()
        #
        # # search the first slice
        # try:
        #     found = False
        #
        #     # use current key as a starting point for the search
        #     if not found:
        #         print('backward')
        #         for j, k in enumerate(self.db.iterator(start=bytes(key.get_key()), include_value=False, reverse=True)):
        #             if j > 5000:
        #                 break
        #
        #             w_key.set_key(k)
        #             w_key.disassemble_key()
        #             #print(w_key.get_key())
        #
        #             if key.get_seg_uid() != w_key.get_seg_uid():
        #                 break
        #
        #             if w_key.get_slice_mod() == mod \
        #                     and w_key.get_slice_count() == 0:
        #                 # found it
        #                 found_key.set_key(w_key.get_key())
        #                 found_key.disassemble_key()
        #                 found = True
        #                 break
        #
        #     # now search backward
        #     if not found:
        #         print('now forward')
        #         for j, k in enumerate(self.db.iterator(start=bytes(key.get_key()), include_value=False)):
        #             if j > 5000:
        #                 break
        #
        #             w_key.set_key(k)
        #             w_key.disassemble_key()
        #             #print(w_key.get_key())
        #
        #             if key.get_seg_uid() != w_key.get_seg_uid():
        #                 break
        #
        #             if w_key.get_slice_mod() == mod \
        #                     and w_key.get_slice_count() == 0 \
        #                     and key.get_seg_uid() == w_key.get_seg_uid():
        #                 # found it
        #                 found_key.set_key(w_key.get_key())
        #                 found_key.disassemble_key()
        #                 found = True
        #                 break
        #
        #     if found:
        #         slices.append(self.read_img(found_key))
        #     else:
        #         raise ValueError("Can't find starting slice.")
        # except:
        #     raise ValueError("Can't find starting slice: " + key.get_key())

        # now iterate over the slices until the end is reached
        i = 0
        for k, v in self.db:
            i += 1
            if i % 200 == 0:
                print(i)

            w_key.set_key(k)
            w_key.disassemble_key()

            if key.get_slice_mod() != mod:
                # wrong slice mod
                continue

            if key.get_slice_type() != w_key.get_slice_type():
                # wrong slice type
                continue

            if key.get_type() != w_key.get_type():
                # wrong type
                continue

            if key.get_seg_uid() == w_key.get_seg_uid():
                # append slice
                slices.update({w_key.get_slice_count(): self.datum_to_img(v)})
                #slices.append(self.datum_to_img(v))

        for key, value in sorted(slices.items()):
            stack.append(value)

        # add up slices to volume
        vol = np.dstack(tuple(stack))

        # swap axes depending on slicing
        if key.get_slice_type() == 'xy':
            return vol
        elif key.get_slice_type() == 'xz':
            vol = np.swapaxes(vol, 1, 2)
            return vol
        else:
            vol = np.swapaxes(vol, 0, 2)
            vol = np.swapaxes(vol, 1, 2)
            return vol
#
#
# def main():
#     # # open db
#     # db = plyvel.DB('/tmp/testdb/', create_if_missing=True, write_buffer_size=268435456)
#     #
#     # # add some data
#     # db.put(b'key', b'value')
#     # db.put(b'another-key', b'another-value')
#     #
#     # # print data
#     # print(db.get(b'key'))
#     #
#     # # close db
#     # db.close()
#
#     key = Key()
#     key.set_key('00045678_12345_img_yz_1234_00')
#     key.disassemble_key()
#     key.create_key()
#
#     print(key.get_key())
#     #print(key.slice_count)
#
#     ia = ImageAdapter('/media/ramdisk/test_img')
#
#     # # prepare slice
#     # nh = NiftiDBHelper('/media/nas/sqlitedb/processed/processedFinalOrderedSegmented.sql')
#     # nh.q_random()
#     # for i, slc in enumerate(yz_slices(nh.get_ct_img())):
#     #     key.set_slice_count(i)
#     #     arr = hounsfield_to_byte(slc)
#     #     val = serialize_slice(arr)
#     #     ia.add_batch(key, val, arr.shape[1], arr.shape[0])
#     #
#     # ia.write()
#
#     # read
#     key.set_slice_count(250)
#     img = ia.read_img(key)
#
#     nh.show_slices([img, img])
#     nh.plt.show()
#
#     ia.dump_img(key, '/media/ramdisk')
#
#     # read vol
#     key.set_slice_count(60)
#     vol = ia.read_volume(key)
#
#     nh.show_slices([vol[:,:,320], vol[:,300,:], vol[300, : , :]])
#     nh.plt.show()
#
#
# if __name__ == '__main__':
#     main()