import serial
import mysql.connector
from datetime import datetime

import matplotlib.pyplot as plt
import random
from scipy.signal import find_peaks
import numpy as np
# 25 samples per second (in algorithm.h)
SAMPLE_FREQ = 25
# taking moving average of 4 samples when calculating HR
# in algorithm.h, "DONOT CHANGE" comment is attached
MA_SIZE = 4
# sampling frequency * 4 (in algorithm.h)
BUFFER_SIZE = 100

def insertar(param, valores):
  try:
      cnx = mysql.connector.connect(user='root', password='3.14164510', host='127.0.0.1', database='iot_reto')

      cursor = cnx.cursor()

      if param == 4:
        query_data = (valores[0], valores[1], valores[2])
        query = f"INSERT INTO pulso(valor_pulso, fecha, id_expediente) VALUES(%s, %s, %s);"

      elif param == 2:
        query_data = (valores[0], valores[1], valores[2])
        query = f"INSERT INTO oxigenacion(valor_oxigenacion, fecha, id_expediente) VALUES(%s, %s, %s);"
      elif param == 3:
        query_data = (valores[0], valores[1])
        query = f"INSERT INTO expedientes(id_expediente, fecha) VALUES(%s, %s, %s, %s);"
      elif param == 1:
        query_data = (valores[0], valores[1], valores[2], valores[3], valores[4], valores[5])
        query = f"INSERT INTO personas(id_persona, nombre, edad, sexo, deporte, id_expediente) VALUES(%s, %s, %s, %s, %s, %s);"
 
      cursor.execute(query, query_data)
      cnx.commit()


  except mysql.connector.Error as err:

    if err.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
      print("Something is wrong with your user name or password")
    elif err.errno == mysql.connector.errorcode.ER_BAD_DB_ERROR:
      print("Database does not exist")
    else:
      print(err)
      
  finally:
    if 'cnx' in locals() or 'cnx' in globals():
      cnx.close()

# this assumes ir_data and red_data as np.array
def calc_hr_and_spo2(ir_data, red_data):
    """
    By detecting  peaks of PPG cycle and corresponding AC/DC
    of red/infra-red signal, the an_ratio for the SPO2 is computed.
    """
    # get dc mean
    ir_mean = int(np.mean(ir_data))

    # remove DC mean and inver signal
    # this lets peak detecter detect valley
    x = -1 * (np.array(ir_data) - ir_mean)

    # 4 point moving average
    # x is np.array with int values, so automatically casted to int
    for i in range(x.shape[0] - MA_SIZE):
        x[i] = np.sum(x[i:i+MA_SIZE]) / MA_SIZE

    # calculate threshold
    n_th = int(np.mean(x))
    n_th = 30 if n_th < 30 else n_th  # min allowed
    n_th = 60 if n_th > 60 else n_th  # max allowed

    ir_valley_locs, n_peaks = find_peaks(x, BUFFER_SIZE, n_th, 4, 15)
    # print(ir_valley_locs[:n_peaks], ",", end="")
    peak_interval_sum = 0
    if n_peaks >= 2:
        for i in range(1, n_peaks):
            peak_interval_sum += (ir_valley_locs[i] - ir_valley_locs[i-1])
        peak_interval_sum = int(peak_interval_sum / (n_peaks - 1))
        hr = int(SAMPLE_FREQ * 60 / peak_interval_sum)
        hr_valid = True
    else:
        hr = -999  # unable to calculate because # of peaks are too small
        hr_valid = False

    # ---------spo2---------

    # find precise min near ir_valley_locs (???)
    exact_ir_valley_locs_count = n_peaks

    # find ir-red DC and ir-red AC for SPO2 calibration ratio
    # find AC/DC maximum of raw

    # FIXME: needed??
    for i in range(exact_ir_valley_locs_count):
        if ir_valley_locs[i] > BUFFER_SIZE:
            spo2 = -999  # do not use SPO2 since valley loc is out of range
            spo2_valid = False
            return hr, hr_valid, spo2, spo2_valid

    i_ratio_count = 0
    ratio = []

    # find max between two valley locations
    # and use ratio between AC component of Ir and Red DC component of Ir and Red for SpO2
    red_dc_max_index = -1
    ir_dc_max_index = -1
    for k in range(exact_ir_valley_locs_count-1):
        red_dc_max = -16777216
        ir_dc_max = -16777216
        if ir_valley_locs[k+1] - ir_valley_locs[k] > 3:
            for i in range(ir_valley_locs[k], ir_valley_locs[k+1]):
                if ir_data[i] > ir_dc_max:
                    ir_dc_max = ir_data[i]
                    ir_dc_max_index = i
                if red_data[i] > red_dc_max:
                    red_dc_max = red_data[i]
                    red_dc_max_index = i

            red_ac = int((red_data[ir_valley_locs[k+1]] - red_data[ir_valley_locs[k]]) * (red_dc_max_index - ir_valley_locs[k]))
            red_ac = red_data[ir_valley_locs[k]] + int(red_ac / (ir_valley_locs[k+1] - ir_valley_locs[k]))
            red_ac = red_data[red_dc_max_index] - red_ac  # subtract linear DC components from raw

            ir_ac = int((ir_data[ir_valley_locs[k+1]] - ir_data[ir_valley_locs[k]]) * (ir_dc_max_index - ir_valley_locs[k]))
            ir_ac = ir_data[ir_valley_locs[k]] + int(ir_ac / (ir_valley_locs[k+1] - ir_valley_locs[k]))
            ir_ac = ir_data[ir_dc_max_index] - ir_ac  # subtract linear DC components from raw

            nume = red_ac * ir_dc_max
            denom = ir_ac * red_dc_max
            if (denom > 0 and i_ratio_count < 5) and nume != 0:
                # original cpp implementation uses overflow intentionally.
                # but at 64-bit OS, Pyhthon 3.X uses 64-bit int and nume*100/denom does not trigger overflow
                # so using bit operation ( &0xffffffff ) is needed
                ratio.append(int(((nume * 100) & 0xffffffff) / denom))
                i_ratio_count += 1

    # choose median value since PPG signal may vary from beat to beat
    ratio = sorted(ratio)  # sort to ascending order
    mid_index = int(i_ratio_count / 2)

    ratio_ave = 0
    if mid_index > 1:
        ratio_ave = int((ratio[mid_index-1] + ratio[mid_index])/2)
    else:
        if len(ratio) != 0:
            ratio_ave = ratio[mid_index]

    # why 184?
    # print("ratio average: ", ratio_ave)
    if ratio_ave > 2 and ratio_ave < 184:
        # -45.060 * ratioAverage * ratioAverage / 10000 + 30.354 * ratioAverage / 100 + 94.845
        spo2 = -45.060 * (ratio_ave**2) / 10000.0 + 30.054 * ratio_ave / 100.0 + 94.845
        spo2_valid = True
    else:
        spo2 = -999
        spo2_valid = False

    return hr, hr_valid, spo2, spo2_valid


def find_peaks(x, size, min_height, min_dist, max_num):
    """
    Find at most MAX_NUM peaks above MIN_HEIGHT separated by at least MIN_DISTANCE
    """
    ir_valley_locs, n_peaks = find_peaks_above_min_height(x, size, min_height, max_num)
    ir_valley_locs, n_peaks = remove_close_peaks(n_peaks, ir_valley_locs, x, min_dist)

    n_peaks = min([n_peaks, max_num])

    return ir_valley_locs, n_peaks


def find_peaks_above_min_height(x, size, min_height, max_num):
    """
    Find all peaks above MIN_HEIGHT
    """

    i = 0
    n_peaks = 0
    ir_valley_locs = []  # [0 for i in range(max_num)]
    while i < size - 1:
        if x[i] > min_height and x[i] > x[i-1]:  # find the left edge of potential peaks
            n_width = 1
            # original condition i+n_width < size may cause IndexError
            # so I changed the condition to i+n_width < size - 1
            while i + n_width < size - 1 and x[i] == x[i+n_width]:  # find flat peaks
                n_width += 1
            if x[i] > x[i+n_width] and n_peaks < max_num:  # find the right edge of peaks
                # ir_valley_locs[n_peaks] = i
                ir_valley_locs.append(i)
                n_peaks += 1  # original uses post increment
                i += n_width + 1
            else:
                i += n_width
        else:
            i += 1

    return ir_valley_locs, n_peaks


def remove_close_peaks(n_peaks, ir_valley_locs, x, min_dist):
    """
    Remove peaks separated by less than MIN_DISTANCE
    """

    # should be equal to maxim_sort_indices_descend
    # order peaks from large to small
    # should ignore index:0
    sorted_indices = sorted(ir_valley_locs, key=lambda i: x[i])
    sorted_indices.reverse()

    # this "for" loop expression does not check finish condition
    # for i in range(-1, n_peaks):
    i = -1
    while i < n_peaks:
        old_n_peaks = n_peaks
        n_peaks = i + 1
        # this "for" loop expression does not check finish condition
        # for j in (i + 1, old_n_peaks):
        j = i + 1
        while j < old_n_peaks:
            n_dist = (sorted_indices[j] - sorted_indices[i]) if i != -1 else (sorted_indices[j] + 1)  # lag-zero peak of autocorr is at index -1
            if n_dist > min_dist or n_dist < -1 * min_dist:
                sorted_indices[n_peaks] = sorted_indices[j]
                n_peaks += 1  # original uses post increment
            j += 1
        i += 1

    sorted_indices[:n_peaks] = sorted(sorted_indices[:n_peaks])

    return sorted_indices, n_peaks

def smooth_curve_test(points, sample_size):
    smoothed_points = []
    reads = [0 for _ in range(sample_size)]
    id_reads = 0
    for id, point in enumerate(points):
        reads[id_reads] = point
        id_reads += 1

        if id_reads % sample_size == 0:
            id_reads = 0
            smoothed_points.append((sum(reads)/sample_size, id))

    return smoothed_points

def smooth_curve_average(points, sample_size):
    smoothed_points = [] 
    psm = sum(points[:sample_size]) / sample_size
    smoothed_points += sample_size * [psm]

    for id in range(sample_size, len(points)):
        previous = smoothed_points[-1] 
        smoothed_points.append(previous + (points[id] - points[id-sample_size])/ sample_size)

    return smoothed_points

def smooth_curve_exponential(points, factor=0.9): 
    smoothed_points = [] 
    for point in points: 
        if smoothed_points: 
            previous = smoothed_points[-1] 
            smoothed_points.append(previous * factor + point * (1 - factor))
        else: 
            smoothed_points.append(point) 
    
    return smoothed_points

def smooth_curve_average(points, sample_size):
    smoothed_points = [] 
    psm = sum(points[:sample_size]) / sample_size
    smoothed_points += sample_size * [psm]

    for id in range(sample_size, len(points)):
        previous = smoothed_points[-1] 
        smoothed_points.append(previous + (points[id] - points[id-sample_size])/ sample_size)

random.seed(0)

def analisisHR():
    global hrValues
    global miliValues
    '''for i in range(0, 96):
        valores.append((hrValues[i]+hrValues[i+1]+hrValues[i+2])/3);
        valoresMili.append((miliValues[i]+miliValues[i+1]+miliValues[i+2])/3)'''
    nuevosValores1= smooth_curve_test(hrValues, 15)
    nuevosValores=[i for (i,j) in nuevosValores1 ]
    len(nuevosValores)
    peaks = find_peaks(nuevosValores)[0]
    
    plt.plot(nuevosValores)
    #print(peaks)
    plt.scatter(peaks, [nuevosValores[j] for j in peaks], marker='+', c='Red')
    #plt.show()
    #print(len(nuevosValores));
    bajada=False
    palpitacionAnterior=-1
    palpitaciones=[]
    for i in range(0, len(peaks)-1):
        palpitaciones.append(miliValues[peaks[i+1]]-miliValues[peaks[i]]);
    print(palpitaciones)
    tiempoPromedio=sum(palpitaciones)/len(palpitaciones)
    valorHR=(60*len(peaks))/(miliValues[-1]-miliValues[0])
    print("duracion:", miliValues[-1]-miliValues[0], valorHR)

ser=serial.Serial("COM4", 9600)
hrValues=[]
miliValues=[]
redValues=[]
irValues=[]
now = datetime.now()

while(1):
    try:
        lineBytes=ser.readline()
        line=lineBytes.decode("ascii")
        line=line.rstrip();#HR:118;ML:1704
        #print(line)
        medidas=line.split(";") #["HR:118", "ML:1704"]
        hr=int(medidas[0].split(":")[1]) #["HR", "118"], toma el 118, lo convierte a int y lo guarda
        milis=int(medidas[1].split(":")[1]) #["ML", "1704"]
        red=int(medidas[2].split(":")[1])
        ir=int(medidas[3].split(":")[1])
        hrValues.append(hr)
        miliValues.append(milis)
        redValues.append(red)
        irValues.append(ir)

    except:
        continue

    if(len(hrValues)==100):
        (hrCalculated, hrValid, spoCalculated, spoValid)=calc_hr_and_spo2(irValues, redValues)
        print(spoValid,":",spoCalculated)
        #print(irValues)
        #print(redValues)
        #analisisHR()
        hrValues=hrValues[25:]
        miliValues=miliValues[25:]
        redValues=redValues[25:]
        irValues=irValues[25:]
        date_time = now.strftime("%Y/%m/%d %H:%M:%S")
        #print("date and time =", dt_string)
        #insertar(2, [spoCalculated, date_time,'10'])
        if spoValid == True:
            for i in range (10):
                #insertar(4, [spoCalculated, date_time,'50'])
                ser.write(str(spoCalculated).encode())
    
    #print(hr)   
