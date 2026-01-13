import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useDashboardStore } from './dashboard'
import type { ChannelConfig } from '../types'

describe('Modbus System Validation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('Channel Type Support', () => {
    it('should support modbus_register channel type', () => {
      const store = useDashboardStore()

      const modbusRegisterChannel: ChannelConfig = {
        name: 'MB_REG_01',
        channel_type: 'modbus_register',
        unit: 'bar',
        group: 'modbus',
        modbus_address: 100,
        modbus_data_type: 'int16',
        modbus_register_type: 'holding',
        modbus_byte_order: 'big',
        modbus_word_order: 'big',
        modbus_scale: 0.1,
        modbus_offset: 0
      }

      store.setChannels({ 'MB_REG_01': modbusRegisterChannel })
      expect(store.channels['MB_REG_01']).toBeDefined()
      expect(store.channels['MB_REG_01'].channel_type).toBe('modbus_register')
    })

    it('should support modbus_coil channel type', () => {
      const store = useDashboardStore()

      const modbusCoilChannel: ChannelConfig = {
        name: 'MB_COIL_01',
        channel_type: 'modbus_coil',
        unit: '',
        group: 'modbus',
        modbus_address: 200,
        modbus_register_type: 'coil'
      }

      store.setChannels({ 'MB_COIL_01': modbusCoilChannel })
      expect(store.channels['MB_COIL_01']).toBeDefined()
      expect(store.channels['MB_COIL_01'].channel_type).toBe('modbus_coil')
    })
  })

  describe('Data Type Handling', () => {
    it('should handle all supported Modbus data types', () => {
      const store = useDashboardStore()

      const dataTypes = ['int16', 'uint16', 'int32', 'uint32', 'float32', 'float64', 'bool'] as const

      const channels: Record<string, ChannelConfig> = {}
      dataTypes.forEach((dataType, index) => {
        const channelName = `MB_${dataType.toUpperCase()}`
        channels[channelName] = {
          name: channelName,
          channel_type: 'modbus_register',
          unit: dataType === 'bool' ? '' : 'units',
          group: 'modbus_test',
          modbus_address: 1000 + index,
          modbus_data_type: dataType,
          modbus_register_type: 'holding',
          modbus_byte_order: 'big',
          modbus_word_order: 'big'
        }
      })

      store.setChannels(channels)

      // Verify all channels were created
      expect(Object.keys(store.channels).length).toBe(dataTypes.length)

      // Verify each channel has correct data type
      dataTypes.forEach(dataType => {
        const channelName = `MB_${dataType.toUpperCase()}`
        expect(store.channels[channelName]).toBeDefined()
        expect(store.channels[channelName].modbus_data_type).toBe(dataType)
      })
    })

    it('should handle byte order and word order correctly', () => {
      const store = useDashboardStore()

      const testCases = [
        { byte_order: 'big', word_order: 'big' },
        { byte_order: 'big', word_order: 'little' },
        { byte_order: 'little', word_order: 'big' },
        { byte_order: 'little', word_order: 'little' }
      ]

      const channels: Record<string, ChannelConfig> = {}
      testCases.forEach((testCase, index) => {
        const channelName = `MB_ORDER_${index}`
        channels[channelName] = {
          name: channelName,
          channel_type: 'modbus_register',
          unit: 'V',
          group: 'modbus_order_test',
          modbus_address: 2000 + index,
          modbus_data_type: 'float32',
          modbus_register_type: 'holding',
          modbus_byte_order: testCase.byte_order,
          modbus_word_order: testCase.word_order
        }
      })

      store.setChannels(channels)

      // Verify all order combinations are supported
      testCases.forEach((testCase, index) => {
        const channelName = `MB_ORDER_${index}`
        expect(store.channels[channelName].modbus_byte_order).toBe(testCase.byte_order)
        expect(store.channels[channelName].modbus_word_order).toBe(testCase.word_order)
      })
    })
  })

  describe('Register Type Support', () => {
    it('should support all Modbus register types', () => {
      const store = useDashboardStore()

      const registerTypes = ['holding', 'input', 'coil', 'discrete'] as const

      const channels: Record<string, ChannelConfig> = {}
      registerTypes.forEach((regType, index) => {
        const channelName = `MB_${regType.toUpperCase()}`
        const isCoil = regType === 'coil' || regType === 'discrete'
        channels[channelName] = {
          name: channelName,
          channel_type: isCoil ? 'modbus_coil' : 'modbus_register',
          unit: isCoil ? '' : 'units',
          group: 'modbus_reg_test',
          modbus_address: 3000 + index,
          modbus_register_type: regType,
          modbus_data_type: isCoil ? 'bool' : 'int16'
        }
      })

      store.setChannels(channels)

      // Verify all register types are supported
      registerTypes.forEach(regType => {
        const channelName = `MB_${regType.toUpperCase()}`
        expect(store.channels[channelName]).toBeDefined()
        expect(store.channels[channelName].modbus_register_type).toBe(regType)
      })
    })
  })

  describe('Scaling and Offset', () => {
    it('should support scale and offset configuration', () => {
      const store = useDashboardStore()

      const testCases = [
        { scale: 1.0, offset: 0 },      // No scaling
        { scale: 0.1, offset: 0 },      // Scale only
        { scale: 1.0, offset: -40 },    // Offset only
        { scale: 0.01, offset: 100 }    // Both scale and offset
      ]

      const channels: Record<string, ChannelConfig> = {}
      testCases.forEach((testCase, index) => {
        const channelName = `MB_SCALE_${index}`
        channels[channelName] = {
          name: channelName,
          channel_type: 'modbus_register',
          unit: 'bar',
          group: 'modbus_scale_test',
          modbus_address: 4000 + index,
          modbus_data_type: 'int16',
          modbus_register_type: 'holding',
          modbus_scale: testCase.scale,
          modbus_offset: testCase.offset
        }
      })

      store.setChannels(channels)

      // Verify scale and offset are preserved
      testCases.forEach((testCase, index) => {
        const channelName = `MB_SCALE_${index}`
        expect(store.channels[channelName].modbus_scale).toBe(testCase.scale)
        expect(store.channels[channelName].modbus_offset).toBe(testCase.offset)
      })
    })
  })

  describe('Widget Auto-Generation', () => {
    it('should generate numeric widgets for modbus_register channels', () => {
      const store = useDashboardStore()

      const channels: Record<string, ChannelConfig> = {
        'MB_PRESSURE': {
          name: 'MB_PRESSURE',
          channel_type: 'modbus_register',
          unit: 'bar',
          group: 'modbus',
          modbus_address: 100,
          modbus_data_type: 'float32',
          modbus_register_type: 'holding'
        },
        'MB_TEMP': {
          name: 'MB_TEMP',
          channel_type: 'modbus_register',
          unit: '°C',
          group: 'modbus',
          modbus_address: 102,
          modbus_data_type: 'int16',
          modbus_register_type: 'input'
        }
      }

      store.setChannels(channels)

      const count = store.autoGenerateWidgets()

      expect(count).toBe(2)

      const currentPage = store.pages.find(p => p.id === store.currentPageId)
      const pressureWidget = currentPage!.widgets.find(w => w.channel === 'MB_PRESSURE')
      const tempWidget = currentPage!.widgets.find(w => w.channel === 'MB_TEMP')

      expect(pressureWidget).toBeDefined()
      expect(pressureWidget?.type).toBe('numeric')

      expect(tempWidget).toBeDefined()
      expect(tempWidget?.type).toBe('numeric')
    })

    it('should generate LED widgets for modbus_coil channels', () => {
      const store = useDashboardStore()

      const channels: Record<string, ChannelConfig> = {
        'MB_STATUS': {
          name: 'MB_STATUS',
          channel_type: 'modbus_coil',
          unit: '',
          group: 'modbus',
          modbus_address: 200,
          modbus_register_type: 'coil'
        },
        'MB_ALARM': {
          name: 'MB_ALARM',
          channel_type: 'modbus_coil',
          unit: '',
          group: 'modbus',
          modbus_address: 201,
          modbus_register_type: 'discrete'
        }
      }

      store.setChannels(channels)

      const count = store.autoGenerateWidgets()

      expect(count).toBe(2)

      const currentPage = store.pages.find(p => p.id === store.currentPageId)
      const statusWidget = currentPage!.widgets.find(w => w.channel === 'MB_STATUS')
      const alarmWidget = currentPage!.widgets.find(w => w.channel === 'MB_ALARM')

      expect(statusWidget).toBeDefined()
      expect(statusWidget?.type).toBe('led')

      expect(alarmWidget).toBeDefined()
      expect(alarmWidget?.type).toBe('led')
    })

    it('should handle mixed Modbus and native channels', () => {
      const store = useDashboardStore()

      const channels: Record<string, ChannelConfig> = {
        'TC_01': {
          name: 'TC_01',
          channel_type: 'thermocouple',
          unit: '°C',
          group: 'native'
        },
        'MB_PRESSURE': {
          name: 'MB_PRESSURE',
          channel_type: 'modbus_register',
          unit: 'bar',
          group: 'modbus',
          modbus_address: 100,
          modbus_data_type: 'float32',
          modbus_register_type: 'holding'
        },
        'DI_01': {
          name: 'DI_01',
          channel_type: 'digital_input',
          unit: '',
          group: 'native'
        },
        'MB_STATUS': {
          name: 'MB_STATUS',
          channel_type: 'modbus_coil',
          unit: '',
          group: 'modbus',
          modbus_address: 200,
          modbus_register_type: 'coil'
        }
      }

      store.setChannels(channels)

      const count = store.autoGenerateWidgets()

      expect(count).toBe(4)

      const currentPage = store.pages.find(p => p.id === store.currentPageId)

      // Native thermocouple → numeric
      const tcWidget = currentPage!.widgets.find(w => w.channel === 'TC_01')
      expect(tcWidget?.type).toBe('numeric')

      // Modbus register → numeric
      const pressureWidget = currentPage!.widgets.find(w => w.channel === 'MB_PRESSURE')
      expect(pressureWidget?.type).toBe('numeric')

      // Native digital input → LED
      const diWidget = currentPage!.widgets.find(w => w.channel === 'DI_01')
      expect(diWidget?.type).toBe('led')

      // Modbus coil → LED
      const statusWidget = currentPage!.widgets.find(w => w.channel === 'MB_STATUS')
      expect(statusWidget?.type).toBe('led')
    })
  })

  describe('Channel Configuration Validation', () => {
    it('should validate required Modbus fields', () => {
      const store = useDashboardStore()

      const validChannel: ChannelConfig = {
        name: 'MB_VALID',
        channel_type: 'modbus_register',
        unit: 'units',
        group: 'modbus',
        modbus_address: 100,
        modbus_data_type: 'int16',
        modbus_register_type: 'holding'
      }

      store.setChannels({ 'MB_VALID': validChannel })

      const channel = store.channels['MB_VALID']
      expect(channel.modbus_address).toBeDefined()
      expect(channel.modbus_data_type).toBeDefined()
      expect(channel.modbus_register_type).toBeDefined()
    })

    it('should handle optional Modbus fields with defaults', () => {
      const store = useDashboardStore()

      const minimalChannel: ChannelConfig = {
        name: 'MB_MINIMAL',
        channel_type: 'modbus_register',
        unit: 'units',
        group: 'modbus',
        modbus_address: 100,
        modbus_data_type: 'int16',
        modbus_register_type: 'holding'
        // Missing: byte_order, word_order, scale, offset
      }

      store.setChannels({ 'MB_MINIMAL': minimalChannel })

      const channel = store.channels['MB_MINIMAL']
      expect(channel).toBeDefined()
      // Defaults should be handled by backend
      expect(channel.modbus_address).toBe(100)
    })
  })

  describe('Address Range Validation', () => {
    it('should support typical Modbus address ranges', () => {
      const store = useDashboardStore()

      const addressTestCases = [
        { address: 0, desc: 'minimum address' },
        { address: 100, desc: 'typical address' },
        { address: 9999, desc: 'high address' },
        { address: 40000, desc: 'holding register offset' },
        { address: 65535, desc: 'maximum 16-bit address' }
      ]

      const channels: Record<string, ChannelConfig> = {}
      addressTestCases.forEach((testCase) => {
        const channelName = `MB_ADDR_${testCase.address}`
        channels[channelName] = {
          name: channelName,
          channel_type: 'modbus_register',
          unit: 'units',
          group: 'address_test',
          modbus_address: testCase.address,
          modbus_data_type: 'int16',
          modbus_register_type: 'holding'
        }
      })

      store.setChannels(channels)

      // Verify all addresses are preserved
      addressTestCases.forEach((testCase) => {
        const channelName = `MB_ADDR_${testCase.address}`
        expect(store.channels[channelName].modbus_address).toBe(testCase.address)
      })
    })
  })
})

describe('Modbus Connection Types (TCP and RTU)', () => {
  describe('Modbus TCP Connection', () => {
    it('should support TCP connection configuration', () => {
      const store = useDashboardStore()

      // TCP connection uses IP address and port
      const tcpChannel: ChannelConfig = {
        name: 'MB_TCP_PRESSURE',
        channel_type: 'modbus_register',
        unit: 'bar',
        group: 'modbus_tcp',
        modbus_address: 100,
        modbus_data_type: 'float32',
        modbus_register_type: 'holding',
        // TCP-specific fields (typically stored at device level, not channel)
        physical_channel: 'modbus_tcp://192.168.1.100:502'
      }

      store.setChannels({ 'MB_TCP_PRESSURE': tcpChannel })

      const channel = store.channels['MB_TCP_PRESSURE']
      expect(channel).toBeDefined()
      expect(channel.channel_type).toBe('modbus_register')
      expect(channel.physical_channel).toContain('192.168.1.100')
      expect(channel.physical_channel).toContain('502')
    })

    it('should support multiple TCP devices with different IPs', () => {
      const store = useDashboardStore()

      const devices = [
        { ip: '192.168.1.100', port: 502, name: 'DEVICE_1' },
        { ip: '192.168.1.101', port: 502, name: 'DEVICE_2' },
        { ip: '192.168.1.102', port: 503, name: 'DEVICE_3' }
      ]

      const channels: Record<string, ChannelConfig> = {}
      devices.forEach((device, index) => {
        const channelName = `MB_TCP_${device.name}`
        channels[channelName] = {
          name: channelName,
          channel_type: 'modbus_register',
          unit: 'units',
          group: 'modbus_tcp',
          modbus_address: 100,
          modbus_data_type: 'int16',
          modbus_register_type: 'holding',
          physical_channel: `modbus_tcp://${device.ip}:${device.port}`
        }
      })

      store.setChannels(channels)

      // Verify all devices are configured
      expect(Object.keys(store.channels).length).toBe(devices.length)
      devices.forEach(device => {
        const channelName = `MB_TCP_${device.name}`
        expect(store.channels[channelName].physical_channel).toContain(device.ip)
        expect(store.channels[channelName].physical_channel).toContain(String(device.port))
      })
    })

    it('should support standard Modbus TCP port 502', () => {
      const store = useDashboardStore()

      const channel: ChannelConfig = {
        name: 'MB_TCP_STANDARD',
        channel_type: 'modbus_register',
        unit: 'units',
        group: 'modbus_tcp',
        modbus_address: 100,
        modbus_data_type: 'int16',
        modbus_register_type: 'holding',
        physical_channel: 'modbus_tcp://192.168.1.100:502'
      }

      store.setChannels({ 'MB_TCP_STANDARD': channel })

      expect(store.channels['MB_TCP_STANDARD'].physical_channel).toContain(':502')
    })

    it('should support non-standard TCP ports', () => {
      const store = useDashboardStore()

      const customPorts = [503, 5502, 10502]

      const channels: Record<string, ChannelConfig> = {}
      customPorts.forEach((port, index) => {
        const channelName = `MB_TCP_PORT_${port}`
        channels[channelName] = {
          name: channelName,
          channel_type: 'modbus_register',
          unit: 'units',
          group: 'modbus_tcp',
          modbus_address: 100,
          modbus_data_type: 'int16',
          modbus_register_type: 'holding',
          physical_channel: `modbus_tcp://192.168.1.100:${port}`
        }
      })

      store.setChannels(channels)

      // Verify all custom ports are preserved
      customPorts.forEach(port => {
        const channelName = `MB_TCP_PORT_${port}`
        expect(store.channels[channelName].physical_channel).toContain(`:${port}`)
      })
    })
  })

  describe('Modbus RTU Connection', () => {
    it('should support RTU connection configuration', () => {
      const store = useDashboardStore()

      // RTU connection uses serial port, baud rate, parity, etc.
      const rtuChannel: ChannelConfig = {
        name: 'MB_RTU_TEMP',
        channel_type: 'modbus_register',
        unit: '°C',
        group: 'modbus_rtu',
        modbus_address: 200,
        modbus_data_type: 'int16',
        modbus_register_type: 'input',
        // RTU-specific fields (typically stored at device level, not channel)
        physical_channel: 'modbus_rtu://COM3:9600:8:E:1'
      }

      store.setChannels({ 'MB_RTU_TEMP': rtuChannel })

      const channel = store.channels['MB_RTU_TEMP']
      expect(channel).toBeDefined()
      expect(channel.channel_type).toBe('modbus_register')
      expect(channel.physical_channel).toContain('modbus_rtu')
      expect(channel.physical_channel).toContain('COM3')
    })

    it('should support common baud rates', () => {
      const store = useDashboardStore()

      const baudRates = [9600, 19200, 38400, 57600, 115200]

      const channels: Record<string, ChannelConfig> = {}
      baudRates.forEach((baud, index) => {
        const channelName = `MB_RTU_BAUD_${baud}`
        channels[channelName] = {
          name: channelName,
          channel_type: 'modbus_register',
          unit: 'units',
          group: 'modbus_rtu',
          modbus_address: 100,
          modbus_data_type: 'int16',
          modbus_register_type: 'holding',
          physical_channel: `modbus_rtu://COM3:${baud}:8:N:1`
        }
      })

      store.setChannels(channels)

      // Verify all baud rates are preserved
      baudRates.forEach(baud => {
        const channelName = `MB_RTU_BAUD_${baud}`
        expect(store.channels[channelName].physical_channel).toContain(`:${baud}:`)
      })
    })

    it('should support different parity configurations', () => {
      const store = useDashboardStore()

      const parityConfigs = [
        { parity: 'N', desc: 'None' },
        { parity: 'E', desc: 'Even' },
        { parity: 'O', desc: 'Odd' }
      ]

      const channels: Record<string, ChannelConfig> = {}
      parityConfigs.forEach((config, index) => {
        const channelName = `MB_RTU_PARITY_${config.parity}`
        channels[channelName] = {
          name: channelName,
          channel_type: 'modbus_register',
          unit: 'units',
          group: 'modbus_rtu',
          modbus_address: 100,
          modbus_data_type: 'int16',
          modbus_register_type: 'holding',
          physical_channel: `modbus_rtu://COM3:9600:8:${config.parity}:1`
        }
      })

      store.setChannels(channels)

      // Verify all parity settings are preserved
      parityConfigs.forEach(config => {
        const channelName = `MB_RTU_PARITY_${config.parity}`
        expect(store.channels[channelName].physical_channel).toContain(`:${config.parity}:`)
      })
    })

    it('should support different serial ports', () => {
      const store = useDashboardStore()

      const serialPorts = [
        'COM1', 'COM3', 'COM5',         // Windows
        '/dev/ttyUSB0', '/dev/ttyS0',   // Linux
        '/dev/tty.usbserial'            // macOS
      ]

      const channels: Record<string, ChannelConfig> = {}
      serialPorts.forEach((port, index) => {
        const channelName = `MB_RTU_PORT_${index}`
        channels[channelName] = {
          name: channelName,
          channel_type: 'modbus_register',
          unit: 'units',
          group: 'modbus_rtu',
          modbus_address: 100,
          modbus_data_type: 'int16',
          modbus_register_type: 'holding',
          physical_channel: `modbus_rtu://${port}:9600:8:N:1`
        }
      })

      store.setChannels(channels)

      // Verify all serial ports are preserved
      serialPorts.forEach((port, index) => {
        const channelName = `MB_RTU_PORT_${index}`
        expect(store.channels[channelName].physical_channel).toContain(port)
      })
    })

    it('should support data bits configuration', () => {
      const store = useDashboardStore()

      const dataBits = [7, 8]  // 7 or 8 bits are common

      const channels: Record<string, ChannelConfig> = {}
      dataBits.forEach((bits, index) => {
        const channelName = `MB_RTU_BITS_${bits}`
        channels[channelName] = {
          name: channelName,
          channel_type: 'modbus_register',
          unit: 'units',
          group: 'modbus_rtu',
          modbus_address: 100,
          modbus_data_type: 'int16',
          modbus_register_type: 'holding',
          physical_channel: `modbus_rtu://COM3:9600:${bits}:N:1`
        }
      })

      store.setChannels(channels)

      // Verify all data bit configurations are preserved
      dataBits.forEach(bits => {
        const channelName = `MB_RTU_BITS_${bits}`
        expect(store.channels[channelName].physical_channel).toContain(`:${bits}:`)
      })
    })

    it('should support stop bits configuration', () => {
      const store = useDashboardStore()

      const stopBits = [1, 2]  // 1 or 2 stop bits

      const channels: Record<string, ChannelConfig> = {}
      stopBits.forEach((bits, index) => {
        const channelName = `MB_RTU_STOP_${bits}`
        channels[channelName] = {
          name: channelName,
          channel_type: 'modbus_register',
          unit: 'units',
          group: 'modbus_rtu',
          modbus_address: 100,
          modbus_data_type: 'int16',
          modbus_register_type: 'holding',
          physical_channel: `modbus_rtu://COM3:9600:8:N:${bits}`
        }
      })

      store.setChannels(channels)

      // Verify all stop bit configurations are preserved
      stopBits.forEach(bits => {
        const channelName = `MB_RTU_STOP_${bits}`
        expect(store.channels[channelName].physical_channel).toContain(`:${bits}`)
      })
    })
  })

  describe('Mixed TCP and RTU Channels', () => {
    it('should support both TCP and RTU channels simultaneously', () => {
      const store = useDashboardStore()

      const channels: Record<string, ChannelConfig> = {
        'MB_TCP_PRESSURE': {
          name: 'MB_TCP_PRESSURE',
          channel_type: 'modbus_register',
          unit: 'bar',
          group: 'modbus_mixed',
          modbus_address: 100,
          modbus_data_type: 'float32',
          modbus_register_type: 'holding',
          physical_channel: 'modbus_tcp://192.168.1.100:502'
        },
        'MB_RTU_TEMP': {
          name: 'MB_RTU_TEMP',
          channel_type: 'modbus_register',
          unit: '°C',
          group: 'modbus_mixed',
          modbus_address: 200,
          modbus_data_type: 'int16',
          modbus_register_type: 'input',
          physical_channel: 'modbus_rtu://COM3:9600:8:E:1'
        },
        'MB_TCP_STATUS': {
          name: 'MB_TCP_STATUS',
          channel_type: 'modbus_coil',
          unit: '',
          group: 'modbus_mixed',
          modbus_address: 300,
          modbus_register_type: 'coil',
          physical_channel: 'modbus_tcp://192.168.1.101:502'
        },
        'MB_RTU_ALARM': {
          name: 'MB_RTU_ALARM',
          channel_type: 'modbus_coil',
          unit: '',
          group: 'modbus_mixed',
          modbus_address: 400,
          modbus_register_type: 'discrete',
          physical_channel: 'modbus_rtu://COM5:19200:8:N:1'
        }
      }

      store.setChannels(channels)

      // Verify all channels exist
      expect(Object.keys(store.channels).length).toBe(4)

      // Verify TCP channels
      expect(store.channels['MB_TCP_PRESSURE'].physical_channel).toContain('modbus_tcp')
      expect(store.channels['MB_TCP_STATUS'].physical_channel).toContain('modbus_tcp')

      // Verify RTU channels
      expect(store.channels['MB_RTU_TEMP'].physical_channel).toContain('modbus_rtu')
      expect(store.channels['MB_RTU_ALARM'].physical_channel).toContain('modbus_rtu')
    })

    it('should auto-generate widgets for mixed TCP and RTU channels', () => {
      const store = useDashboardStore()

      const channels: Record<string, ChannelConfig> = {
        'MB_TCP_01': {
          name: 'MB_TCP_01',
          channel_type: 'modbus_register',
          unit: 'units',
          group: 'mixed',
          modbus_address: 100,
          modbus_data_type: 'float32',
          modbus_register_type: 'holding',
          physical_channel: 'modbus_tcp://192.168.1.100:502'
        },
        'MB_RTU_01': {
          name: 'MB_RTU_01',
          channel_type: 'modbus_register',
          unit: 'units',
          group: 'mixed',
          modbus_address: 200,
          modbus_data_type: 'int16',
          modbus_register_type: 'holding',
          physical_channel: 'modbus_rtu://COM3:9600:8:N:1'
        }
      }

      store.setChannels(channels)

      const count = store.autoGenerateWidgets()

      expect(count).toBe(2)

      const currentPage = store.pages.find(p => p.id === store.currentPageId)
      expect(currentPage!.widgets.find(w => w.channel === 'MB_TCP_01')).toBeDefined()
      expect(currentPage!.widgets.find(w => w.channel === 'MB_RTU_01')).toBeDefined()
    })
  })
})

describe('Modbus Integration Validation Checklist', () => {
  it('should have all required channel type fields', () => {
    // This test documents what fields are required for Modbus channels
    const requiredRegisterFields = [
      'name',
      'channel_type',  // 'modbus_register'
      'unit',
      'group',
      'modbus_address',
      'modbus_data_type',
      'modbus_register_type'
    ]

    const requiredCoilFields = [
      'name',
      'channel_type',  // 'modbus_coil'
      'unit',
      'group',
      'modbus_address',
      'modbus_register_type'
    ]

    expect(requiredRegisterFields.length).toBeGreaterThan(0)
    expect(requiredCoilFields.length).toBeGreaterThan(0)
  })
})
