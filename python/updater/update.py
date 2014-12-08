#!/usr/bin/env python3
#
# Skywriter HAT GestIC Firmware Updater
#
######################################################################
#
# FW_UPDATE_START
#
# Size | Flags | Seq | ID   | CRC | SessionID | IV | UpdateFn | Reserved
# 1      1       1     1    | 4     4           14   1          1
# 0x1c   n/a     n/a   0x80 | Desc below
#
# CRC
# ---
# CRC32, Ethernet. Polynomial 0x04C11DB7
# Calculated across remaining 20 bytes of message
# 32-bit word
#
# SessionID
# ---------
# Random number generated by host, must be present in FW_UPDATE_COMPLETED
# or session will be invalid.
#
# IV
# --
# 14-byte value used to encrypt the data
#
# UpdateFunction
# ---------------
# 0 - Program Flash
# 1 - Verify Only
# If set to verify at this stage, then subsequent block requests can *only*
# verify
#
# Reserved
# --------
# Reserved!
#
#####################################################################
#
# FW_UPDATE_BLOCK
# 
# Size   ...   ID | CRC | Address | Length | UpdateFunction | Payload
# 0x8c       0x81 | 4     2         1        1                128
#
# CRC
# ---
# Calculated over remainder of message ( 132 bytes )
#
# Address
# -------
# Flash address of block which will be programmed/verified
# Lower 4KB reserved by the library loader
# Range: (0x1000..0x7fff)
#
# Length
# ------
# Length of the content block which will be updated
# Range: (0x00..0x80)
#
# UpdateFunction
# --------------
# As above, 0 - Program, 1 - Verify
#
# Payload
# -------
# ALWAYS 128 bytes long. Remainder filled with zeros.
#
######################################################################
#
# FW_UPDATE_COMPLETED
#
# Size  ...   ID | CRC | SessionID | UpdateFunction | FwVersion | Reserved
# 8x88      0x82 | 4     4           1                120         3
#
# CRC
# ---
# Calculated over remaining 128 bytes
#
# SessionID
# ---------
# As above
#
# UpdateFunction
# --------------
# If it was started with ProgramFlash ( 0 ) then it must be finalised
# with ProgramFlash ( 0 ).
#
# 0 - Program Flash
# 1
# 3 - Restart ( Presumably if any verify stage fails )
#
# FwVersion
# ---------
# 120 bytes interpreted as a string, containing Firmware Version

import random, binascii
import fw
import i2c
import time
import RPi.GPIO as GPIO


SW_ADDR      = 0x42
SW_RESET_PIN = 17
SW_XFER_PIN  = 27

FW_UPDATE_START     = 0x80
FW_UPDATE_BLOCK     = 0x81
FW_UPDATE_COMPLETED = 0x82

FW_UPDATE_FN_PROG   = 0
FW_UPDATE_FN_VERIFY = 1

GPIO.setmode(GPIO.BCM)
GPIO.setup(SW_RESET_PIN, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(SW_XFER_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.output(SW_RESET_PIN, GPIO.LOW)
time.sleep(.01)
GPIO.output(SW_RESET_PIN, GPIO.HIGH)
#time.sleep(.3)

class Skyware():
  session_id = 0
  i2c = None

  def i2c_bus_id(self):
    revision = ([l[12:-1] for l in open('/proc/cpuinfo','r').readlines() if l[:8]=="Revision"]+['0000'])[0]
    return 1 if int(revision, 16) >= 4 else 0

  def __init__(self):
    self.session_id = 1 #random.getrandbits(32)
    self.i2c = i2c.I2CMaster(self.i2c_bus_id())

  def i2c_write(self, data):
    #print('Writing packet:',len(data),data)
    self.i2c.transaction(i2c.writing_bytes(SW_ADDR, *data))

  def calculate_crc(self,payload):
    crc = binascii.crc32(bytes(payload))
    #print(crc, bytes(payload))
    return crc

  def update_begin(self, iv, verify_only = False):
    payload = Payload()
    payload.append(0x1c) # Length
    payload.append(0x00) # Flags
    payload.append(0x00) # Seq
    payload.append(FW_UPDATE_START)

    payload.append(0, 4) # Reserve 4 bytes for CRC
    
    payload.append(self.session_id, 4) # Session ID

    payload.append(iv) # 14 0s as encryption key

    if verify_only:
      payload.append(FW_UPDATE_FN_VERIFY)
    else:
      payload.append(FW_UPDATE_FN_PROG) # Set function to program

    payload.append(0)

    crc = self.calculate_crc(payload[8:])
    payload.replace(4,crc,4)
 
    self.i2c_write(payload)
    time.sleep(0.04)
    result = self.handle_exception()
    print("Started",result[0:10])

  def update_complete(self,firmware_version):
    payload = Payload()
    payload.append(0x88) # Length
    payload.append(0x00)
    payload.append(0x00)
    payload.append(FW_UPDATE_COMPLETED)

    payload.append(0, 4) # Reserve 4 bytes for CRC

    payload.append(self.session_id, 4) # Session ID
    
    payload.append(FW_UPDATE_FN_PROG)

    payload.append(firmware_version)
    #payload.append(1,120)
   
    payload.append(0,3)

    crc = self.calculate_crc(payload[8:])
    payload.replace(4,crc,4)
 
    self.i2c_write(payload)
    time.sleep(0.06)
    result = self.handle_exception()
    print( "Completed:", result[0:10] )
  
  def verify_block(self, block_addr, block_len, block_data):
    payload = Payload()
    payload.append(0x8c)
    payload.append(0x00) 
    payload.append(0x00)
    payload.append(FW_UPDATE_BLOCK)
    
    payload.append(0, 4)

    payload.append(block_addr,2) # Address to program
    payload.append(block_len, 1) # Length of block to program
    payload.append(FW_UPDATE_FN_VERIFY) # Set to program
    payload.append(block_data) # Actual payload

    crc = self.calculate_crc(payload[8:])
    payload.replace(4,crc,4)

    self.i2c_write(payload)
   
    time.sleep(0.06)
    result = self.handle_exception()
    if( result[6] == 0x08 ):
      print("Verify Failed!",result[0:10])
    elif( result[6] == 0 ):
      print("Verify OK!",    result[0:10])
      

  def update_block(self, block_addr, block_len, block_data):
    payload = Payload()
    payload.append(0x8c)
    payload.append(0x00) 
    payload.append(0x00)
    payload.append(FW_UPDATE_BLOCK)
    
    payload.append(0, 4)

    payload.append(block_addr,2) # Address to program
    payload.append(block_len, 1) # Length of block to program
    payload.append(FW_UPDATE_FN_PROG) # Set to program
    payload.append(block_data) # Actual payload

    crc = self.calculate_crc(payload[8:])
    payload.replace(4,crc,4)

    self.i2c_write(payload)

    time.sleep(0.06)
    result = self.handle_exception()
    if( result[6] == 0 ):
      print("OK", result[0:10])

  def handle_exception(self):
    '''
     1 - Unknown Command
     2 - Invalid Session ID
     3 - Invalid CRC
     4 - Invalid Length
     5 - Invalid Address
     6 - Invalid Function
     8 - Content Mixmatch
     12- Wrong Param
    '''
    while GPIO.input(SW_XFER_PIN):
      pass
    if not GPIO.input(SW_XFER_PIN):
      GPIO.setup(SW_XFER_PIN, GPIO.OUT, initial=GPIO.LOW)
      data = self.i2c.transaction(i2c.reading(SW_ADDR, 132))
      #print('RESPONSE:', data[0])
      return data[0]
      GPIO.setup(SW_XFER_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

class Payload(list):
  def __init__(self):
    list.__init__(self)

  def replace(self, start, value, size=1):
    if type(value) == int: # or type(value) == long:
      self[start:start+size] = value.to_bytes(length=size,byteorder="little",signed=False)
      #for x in range(size):
      #  self[start+x] = int(value >> (((size-1)*8) - 8*x) & 0xFF)
    elif type(value) == str:
      x = 0
      for char in value:
        self[start+x] = ord(char)
        x+=1
    elif type(value) == list:
      self[start, start+len(value)] = value

  def append(self, value, size=1):
    '''
    Append to the Payload
    value = String, list or integer
    size  = size of supplied integer in bytes
    '''
    if type(value) == int: # or type(value) == long:
      #print('Convert int',value,size)
      for x in value.to_bytes(length=size,byteorder="little",signed=False):
        list.append(self, x)
      #for x in range(size):
      #  list.append(self, int(value >> (((size-1)*8) - 8*x) & 0xFF ))      
    elif type(value) == str:
      for char in value:
        list.append(self, ord(char))    
    elif type(value) == list:
      for item in value:
        list.append(self,item)

updater = Skyware()
updater.handle_exception()

#exit()
print("Starting update...")
updater.update_begin(fw.LDR_IV)

for page in fw.LDR_UPDATE_DATA:
  address = page[0]
  length  = page[1]
  print("Updating addr: ", address)
  updater.update_block(address, length, page[2:])
  #time.sleep(0.06)
  #updater.handle_exception()
  #print("Verifying addr: ", address)
  #updater.verify_block(address, length, page)

print("Finishing update...")
updater.update_complete(fw.LDR_VERSION)

time.sleep(0.5)
print("Resetting...")
GPIO.output(SW_RESET_PIN, GPIO.LOW)
time.sleep(.01)
GPIO.output(SW_RESET_PIN, GPIO.HIGH)
time.sleep(.3)
updater.handle_exception()

for x in range(21):
  time.sleep(1)
  print("...")

print("Starting update...")
updater.update_begin(fw.FW_IV)

for page in fw.FW_UPDATE_DATA:
  address = page[0]
  length  = page[1]
  print("Updating addr: ", address)
  updater.update_block(address, length, page[2:])
  #time.sleep(0.06)
  #updater.handle_exception()
  #print("Verifying addr: ", address)
  #updater.verify_block(address, length, page)

print("Finishing update...")
updater.update_complete(fw.FW_VERSION)


print("Verifying update...")
updater.update_begin(fw.FW_IV,True)
time.sleep(0.06)
updater.handle_exception()

for page in fw.FW_UPDATE_DATA:
  address = page[0]
  length  = page[1]
  print("Verifying addr: ", address)
  updater.verify_block(address, length, page[2:])

print("Resetting...")
GPIO.output(SW_RESET_PIN, GPIO.LOW)
time.sleep(.01)
GPIO.output(SW_RESET_PIN, GPIO.HIGH)
time.sleep(.3)
updater.handle_exception()

