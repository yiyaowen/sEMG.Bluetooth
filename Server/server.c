#include <MKL25Z4.h>

// ADC

#define ADC_CHANNEL_1_PTC (0x01) // PTC1
#define ADC_CHANNEL_2_PTC (0x02) // PTC2
#define ADC_CHANNEL_3_PTB (0x03) // PTB3
#define ADC_CHANNEL_4_PTB (0x02) // PTB2
#define ADC_CHANNEL_5_PTB (0x01) // PTB1
#define ADC_CHANNEL_6_PTB (0x00) // PTB0

#define ADC_CHANNEL_1_INPUT (0x0F) // ADC0_SE15
#define ADC_CHANNEL_2_INPUT (0x0B) // ADC0_SE11
#define ADC_CHANNEL_3_INPUT (0x0D) // ADC0_SE13
#define ADC_CHANNEL_4_INPUT (0x0C) // ADC0_SE12
#define ADC_CHANNEL_5_INPUT (0x09) // ADC0_SE9
#define ADC_CHANNEL_6_INPUT (0x08) // ADC0_SE8

void InitAdc(void);

// 4-0 ADCH: AD Input channel selection.
//
// COCO: Conversion Complete flag.
// ADCx_SC1n's COCO will be set when sampling is finished.
//
#define SELECT_ADC_INPUT(Channel) \
    ADC0->SC1[0] = ADC_CHANNEL_##Channel##_INPUT; \
    while (!(ADC0->SC1[0] & ADC_SC1_COCO_MASK)) ;

// R: Result.
// The sampling result will be stored into Rn register.
#define ADC_INPUT_VALUE ((uint16_t)ADC0->R[0])

// UART

#define UART_RX_PTA (1)
#define UART_TX_PTA (2)

#define UART_BAUD_RATE (9600)

void InitUart(void);

#define UART_WRITABLE (UART0->S1 & 0x80)
#define UART_READABLE (UART0->S1 & 0x20)

#define UART_IO_VALUE (UART0->D)

int main(void)
{
    InitAdc();
    InitUart();
    
    volatile int input_ptr, output_ptr;
    volatile int byte_writen;
    
    // The device [KL25Z128VLK4]'s SRAM is total 16kB available
    // and the stack depth is set to 8kB i.e. 8192 bytes in startup,
    // so allocate 2048 16-bit sampling values i.e. 4096 bytes here.
    uint8_t data_buffer[4096];
    
    // ptr's range: 0 ~ 2047.
    input_ptr = output_ptr = 0;
    byte_writen = 0;
    
    for ( ;; )
    {
        // Get sampling input.
        if (input_ptr + 1 != output_ptr)
        {
            SELECT_ADC_INPUT(1);
            
            // Little-endian, low-byte followed by high-byte.
            data_buffer[2 * input_ptr] = ADC_INPUT_VALUE & 0x0FF;
            data_buffer[2 * input_ptr + 1] = (ADC_INPUT_VALUE >> 8) & 0x0FF;
            
            if (++input_ptr > 2047)
            {
                input_ptr = 0;
            }
        }
        // Send to remote device.
        while (UART_WRITABLE && (output_ptr + 1 != input_ptr))
        {
            if (UART_WRITABLE && byte_writen == 0)
            {
                ++byte_writen;
                UART_IO_VALUE = data_buffer[2 * output_ptr];
            }
            if (UART_WRITABLE && byte_writen == 1)
            {
                ++byte_writen;
                UART_IO_VALUE = data_buffer[2 * output_ptr + 1];
            }
            
            if (byte_writen == 2)
            {
                byte_writen = 0;
                if (++output_ptr > 2047)
                {
                    output_ptr = 0;
                }
            }
        }
    }
}

void InitAdc(void)
{
    SIM->SCGC6 |= (1UL << SIM_SCGC6_ADC0_SHIFT);
    
    // CFG: Configuration (Register).
    //
    // ADICLK: AD Input Clock (Selection).
    //         00: Bus clock = 24 MHz
    //         01: Bus clock / 2 = 12 MHz
    //         10: Alternate clock (ALTCLK)
    //         11: Asynchronous clock (ADACK)
    //
    // MODE: Conversion mode selection.
    //       Use single-ended input mode (DIFF = 0).
    //       00: 8-bit conversion when DIFF = 0
    //       01: 12-bit conversion when DIFF = 0
    //       10: 10-bit conversion when DIFF = 0
    //       11: 16-bit conversion when DIFF = 0
    //
    ADC0->CFG1 = ADC_CFG1_ADICLK(1) | ADC_CFG1_MODE(3);
    
    // SC: Status & Control (Register).
    //
    // ADTRG: AD Trigger (Selection).
    //        0: Software trigger
    //        1: Hardware trigger
    //
    // REFSEL: (Voltage) Reference Selection.
    //         00: Default, external V_REFH & V_REFL
    //         01: Alternate, V_ALTH & V_ALTL
    //
    ADC0->SC2 = ADC_SC2_ADTRG(0) | ADC_SC2_REFSEL(0);
    
    SIM->SCGC5 |= (1UL << SIM_SCGC5_PORTB_SHIFT);
    SIM->SCGC5 |= (1UL << SIM_SCGC5_PORTC_SHIFT);
    
    // All ADC channel-ports should be enabled with ALT0.
    PORTC->PCR[ADC_CHANNEL_1_PTC] &= ~PORT_PCR_MUX_MASK;
    PORTC->PCR[ADC_CHANNEL_2_PTC] &= ~PORT_PCR_MUX_MASK;
    PORTB->PCR[ADC_CHANNEL_3_PTB] &= ~PORT_PCR_MUX_MASK;
    PORTB->PCR[ADC_CHANNEL_4_PTB] &= ~PORT_PCR_MUX_MASK;
    PORTB->PCR[ADC_CHANNEL_5_PTB] &= ~PORT_PCR_MUX_MASK;
    PORTB->PCR[ADC_CHANNEL_6_PTB] &= ~PORT_PCR_MUX_MASK;
}

void InitUart(void)
{
    SIM->SCGC4 |= SIM_SCGC4_UART0_MASK;
    SIM->SCGC5 |= SIM_SCGC5_PORTA_MASK;
    
    // SOPT2: System Options Register 2.
    //
    // UART0SRC:
    //          00 Clk disabled
    //          01 MCGFLLCLK
    //          10 OSCERCLK
    //          11 MCGIRCLK
    //
    // PLLFLLSEL:
    //           0 FLL, no divider
    //           1 PLL, divided by 2
    //
    SIM->SOPT2 |= (SIM_SOPT2_UART0SRC(1) | SIM_SOPT2_PLLFLLSEL(0));

    // PTA1's ALT2 is UART0_RX; PTA2's ALT2 is UART0_TX.
    PORTA->PCR[UART_RX_PTA] = PORT_PCR_MUX(2);
    PORTA->PCR[UART_TX_PTA] = PORT_PCR_MUX(2);
        
    // UARTx_C1 should only be altered
    // when the transmitter and receiver are both disabled.
    UART0->C2 = 0;

    uint32_t divisor = DEFAULT_SYSTEM_CLOCK /
                       (UART_BAUD_RATE * 16);
    // SBR: Set Baud Rate.
    UART0->BDH = UART0_BDH_SBR(divisor >> 8);
    UART0->BDL = UART0_BDL_SBR(divisor);
    
    // 8-bit data, 1-bit stop, no vefify.
    UART0->C1 = UART0->S2 = UART0->C3 = 0;
    UART0->C4 = UART0_C4_OSR(0x0F);
    
    // TE: Transmit Enable; RE: Receive Enable.
    UART0->C2 = UART0_C2_TE_MASK | UART0_C2_RE_MASK;
}
