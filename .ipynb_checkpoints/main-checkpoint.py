# import the necessary packages
import os
import flask
import random
import tensorflow as tf
import matplotlib.pyplot as plt
from flask import Flask, request, redirect, url_for, jsonify, send_file
from werkzeug import secure_filename

MYDIR = os.path.dirname(__file__)
UPLOAD_FOLDER = 'static/uploads/'
COLOR = 'static/colored/'
ALLOWED_EXTENSIONS = set(['png', 'jpg', 'jpeg'])

#----- CONFIG -----#
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['COLOR'] = COLOR
app.config['DEBUG'] = False
app.static_folder = 'static'


##############################################################################################################################################################################################
#-------- MODEL -----------#

# Custom convu filter to downsample image
def downsample(filters, size, apply_batchnorm=True):
    initializer = tf.random_normal_initializer(0., 0.02)

    result = tf.keras.Sequential()
    result.add(
            tf.keras.layers.Conv2D(filters, size, strides=2, padding='same',
                             kernel_initializer=initializer, use_bias=False))

    if apply_batchnorm:
        result.add(tf.keras.layers.BatchNormalization())

    result.add(tf.keras.layers.LeakyReLU())

    return result

# Custom convu filter to upsample image
def upsample(filters, size, apply_dropout=False):
    initializer = tf.random_normal_initializer(0., 0.02)

    result = tf.keras.Sequential()
    result.add(
        tf.keras.layers.Conv2DTranspose(filters, size, strides=2,
                                    padding='same',
                                    kernel_initializer=initializer,
                                    use_bias=False))

    result.add(tf.keras.layers.BatchNormalization())

    if apply_dropout:
        result.add(tf.keras.layers.Dropout(0.5))

    result.add(tf.keras.layers.ReLU())

    return result
def Generator():
    down_stack = [
        downsample(64, 4, apply_batchnorm = False), # (bs, 128, 128, 64)
        downsample(128, 4), # (bs, 64, 64, 128)
        downsample(256, 4), # (bs, 32, 32, 256)
        downsample(256, 4), # (bs, 16, 16, 512)
        downsample(256, 4), # (bs, 8, 8, 512)
        downsample(256, 4), # (bs, 4, 4, 512)
        downsample(512, 4), # (bs, 2, 2, 512)
        downsample(512, 4), # (bs, 1, 1, 512)
          ]

    up_stack = [
        upsample(512, 4, apply_dropout=True), # (bs, 2, 2, 1024)
        upsample(256, 4, apply_dropout=True), # (bs, 4, 4, 1024)
        upsample(256, 4, apply_dropout=True), # (bs, 8, 8, 1024)
        upsample(256, 4), # (bs, 16, 16, 1024)
        upsample(256, 4), # (bs, 32, 32, 512)
        upsample(128, 4), # (bs, 64, 64, 256)
        upsample(64, 4), # (bs, 128, 128, 128)
          ]

    initializer = tf.random_normal_initializer(0., 0.02)
    last = tf.keras.layers.Conv2DTranspose(3, 4,
                                         strides=2,
                                         padding='same',
                                         kernel_initializer=initializer,
                                         activation='tanh') # (bs, 256, 256, 3)

    concat = tf.keras.layers.Concatenate()

    inputs = tf.keras.layers.Input(shape=[None,None,3])
    x = inputs

  # Downsampling through the model
    skips = []
    for down in down_stack:
        x = down(x)
        skips.append(x)

    skips = reversed(skips[:-1])

  # Upsampling and establishing the skip connections
    for up, skip in zip(up_stack, skips):
        x = up(x)
        x = concat([x, skip])

    x = last(x)

    return tf.keras.Model(inputs=inputs, outputs=x)

def Discriminator():
    initializer = tf.random_normal_initializer(0., 0.02)

    inp = tf.keras.layers.Input(shape=[None, None, 3], name='input_image')
    tar = tf.keras.layers.Input(shape=[None, None, 3], name='target_image')

    x = tf.keras.layers.concatenate([inp, tar]) # (bs, 256, 256, channels*2)

    down1 = downsample(64, 4, False)(x) # (bs, 128, 128, 64)
    down2 = downsample(128, 4)(down1) # (bs, 64, 64, 128)
    down3 = downsample(256, 4)(down2) # (bs, 32, 32, 256)

    zero_pad1 = tf.keras.layers.ZeroPadding2D()(down3) # (bs, 34, 34, 256)
    conv = tf.keras.layers.Conv2D(512, 4, strides=1,
                                kernel_initializer=initializer,
                                use_bias=False)(zero_pad1) # (bs, 31, 31, 512)

    batchnorm1 = tf.keras.layers.BatchNormalization()(conv)

    leaky_relu = tf.keras.layers.LeakyReLU()(batchnorm1)

    zero_pad2 = tf.keras.layers.ZeroPadding2D()(leaky_relu) # (bs, 33, 33, 512)

    last = tf.keras.layers.Conv2D(1, 4, strides=1,
                                kernel_initializer=initializer)(zero_pad2) # (bs, 30, 30, 1)

    return tf.keras.Model(inputs=[inp, tar], outputs=last)

# Adam optimizers
#generator_optimizer = tf.train.AdamOptimizer(2e-4, beta1=0.5)
#discriminator_optimizer = tf.train.AdamOptimizer(2e-4, beta1=0.5)
generator_optimizer = tf.optimizers.Adam(2e-4, beta_1=0.5)
discriminator_optimizer = tf.optimizers.Adam(2e-4, beta_1=0.5)

#Create instance of generator and discriminator    
generator = Generator()
discriminator = Discriminator()

#load checkpoint weights
checkpoint_dir = 'static/model_weights'
checkpoint_prefix = os.path.join(checkpoint_dir, "ckpt")
checkpoint = tf.train.Checkpoint(generator_optimizer=generator_optimizer,
                                 discriminator_optimizer=discriminator_optimizer,
                                 generator=generator,
                                 discriminator=discriminator)
#Restore weights
#checkpoint.restore(tf.train.latest_checkpoint(checkpoint_dir))
checkpoint.restore(tf.train.latest_checkpoint(checkpoint_dir))

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

##############################################################################################################################################################################################

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        # if user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            #first remove all files in upload and in color
            for files in os.listdir(os.path.join(app.config['UPLOAD_FOLDER'])):
                os.remove(os.path.join(MYDIR + "/" + app.config['UPLOAD_FOLDER'], files))
            for files in os.listdir('static/colored/'):
                os.remove('static/colored/'+str(files))
            filename = secure_filename(file.filename)
            #file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            file.save(os.path.join(MYDIR + "/" + app.config['UPLOAD_FOLDER'], filename))
            #image = tf.io.read_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image = tf.io.read_file(os.path.join(MYDIR + "/" + app.config['UPLOAD_FOLDER'], filename))
            image = tf.image.decode_jpeg(image)
            image = tf.cast(image, tf.float32)
            image = tf.image.grayscale_to_rgb(tf.image.rgb_to_grayscale(image))
            image = tf.image.resize(image, [256, 256], method=tf.image.ResizeMethod.NEAREST_NEIGHBOR)
            image = (image/127.5) -1
            image = tf.expand_dims(image,0)            
            prediction = generator(image, training=True)
            prediction = prediction[0] * 0.5 + 0.5
            plt.imshow(prediction)
            plt.axis('off')
            plt.savefig('static/colored/'+ str(filename), bbox_inches = 'tight', pad_inches = 0)
            return flask.render_template('results.html', url ='static/colored/'+str(filename), url2 = 'static/uploads/'+str(filename))

    return flask.render_template('index.html')

#----- MAIN SENTINEL -----#
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(port=port)
