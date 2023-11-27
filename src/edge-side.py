from google.cloud import storage

import sys
import os
import pika
import json
from datetime import datetime

from module import rabbitmq
from module import message
from module import database

IMAGE_EXTENTION = '.jpg'
VIDEO_EXTENTION = '.mp4'

ENV_FILE_PATH = '../.env'

LOCAL_IMAGE_DIR = '../resources/images'      # Local path to detected images
LOCAL_VIDEO_DIR = '../resources/videos'      # Local path to detected videos
# Detected images directory in bucket
CLOUD_IMAGE_DIR = 'images'
# Detected videos directory in bucket
CLOUD_VIDEO_DIR = 'videos'


def envFileParser():
    """Read and parse the .env file"""

    with open(ENV_FILE_PATH) as f:
        for line in f:
            if line.strip() and not line.strip().startswith("#"):
                key, value = line.strip().split("=", 1)
                os.environ[key] = value

    global remote_amqp_url
    remote_amqp_url = os.environ.get('AMQP_URL')
    global remote_queue_name
    remote_queue_name = os.environ.get('QUEUE')
    global bucket_name
    bucket_name = os.environ.get('BUCKET')

    if (remote_amqp_url == '' or remote_queue_name == '' or bucket_name == ''):
        return False
    else:
        return True


def sendMessage(message):
    """Send message to the remote AMQP server"""

    # Create a connection to the remote AMQP server using the configuration
    remote_connection_parameters = pika.URLParameters(remote_amqp_url)
    remote_connection = pika.BlockingConnection(remote_connection_parameters)
    remote_channel = remote_connection.channel()

    # Publish the received message to the remote queue
    remote_channel.basic_publish(
        exchange='',
        routing_key=remote_queue_name,
        body=message
    )
    print(f"Sent message to the remote AMQP server: {message}")

    # Close the connection to the remote AMQP server
    remote_connection.close()


def sendImageAndVideo(_message):
    """Send image and video match with timestamp in message"""

    timestamp = message.getTimestampFromMessage(_message)
    if (timestamp != None):
        image_name = timestamp + IMAGE_EXTENTION
        video_name = timestamp + VIDEO_EXTENTION

        if database.searchFileInDirectory(image_name, LOCAL_IMAGE_DIR):
            image_path = os.getcwd() + '/' + LOCAL_IMAGE_DIR + '/' + image_name
            if not rabbitmq.singleBlobUpload(bucket_name, image_path):
                return False
        else:
            print(f"The image: {image_name} is not found.")

        if database.searchFileInDirectory(video_name, LOCAL_VIDEO_DIR):
            video_path = os.getcwd() + '/' + LOCAL_VIDEO_DIR + '/' + video_name
            if not rabbitmq.singleBlobUpload(bucket_name, video_path):
                return False
        else:
            print(f"The video: {video_name} is not found.")
    else:
        print(f"No timestamp found in message")
        return False

    return True


def eventProcessing():
    """
    Recive message from local RabbitMQ server, then:
    1. Publish it to CloudAMQP
    2. Get timestamp, search for image and video with that timestamp, if found, send the image and video to Cloud Storage
    """

    # Define the local AMQP server connection parameters
    local_connection_parameters = pika.ConnectionParameters(
        host='localhost',
        port=5672,
        virtual_host='/',
        credentials=pika.PlainCredentials('guest', 'guest')
    )

    # Create a connection to the local AMQP server
    local_connection = pika.BlockingConnection(local_connection_parameters)
    local_channel = local_connection.channel()

    # Declare the queue to receive messages from
    local_queue_name = 'event'
    local_channel.queue_declare(queue=local_queue_name)

    ###########################################################

    # Define a callback function to process received messages
    def local_callback(ch, method, properties, body):
        sendMessage(body)
        sendImageAndVideo(body)
        ch.basic_ack(delivery_tag=method.delivery_tag)

    ############################################################

    # Set up the consumer and specify the callback function
    local_channel.basic_consume(
        queue=local_queue_name, on_message_callback=local_callback)

    print('Waiting for messages from the local AMQP server. To exit, press CTRL+C')
    try:
        local_channel.start_consuming()
    except KeyboardInterrupt:
        local_channel.stop_consuming()


if envFileParser():
    eventProcessing()
else:
    print(f"Failed to read .env file: {ENV_FILE_PATH}")
